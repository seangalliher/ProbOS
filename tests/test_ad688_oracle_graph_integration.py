"""AD-688: Oracle Graph Integration (Tier 6 + post-merge expansion) tests."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from probos.cognitive.oracle_service import (
    _GRAPH_EXPANSION_DISCOUNT,
    _GRAPH_EXPANSION_PER_PARENT,
    _GRAPH_HOP_PROXIMITY_DIRECT,
    _GRAPH_HOP_PROXIMITY_TWO_HOP,
    OracleResult,
    OracleService,
    _extract_entity_tokens,
)
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
)


def _make_edge(
    *,
    source_id: str,
    target_id: str,
    relation: KnowledgeRelationType = KnowledgeRelationType.MEMBER_OF,
    source_type: KnowledgeEntityType = KnowledgeEntityType.AGENT,
    target_type: KnowledgeEntityType = KnowledgeEntityType.AGENT,
    weight: float = 0.8,
    confidence: float = 0.9,
    edge_id: str | None = None,
) -> KnowledgeEdge:
    kwargs: dict[str, object] = dict(
        source_type=source_type,
        source_id=source_id,
        relation=relation,
        target_type=target_type,
        target_id=target_id,
        weight=weight,
        confidence=confidence,
    )
    if edge_id is not None:
        kwargs["id"] = edge_id
    return KnowledgeEdge(**kwargs)  # type: ignore[arg-type]


class _StubGraph:
    """Programmable KnowledgeEdgeStorage stub."""

    def __init__(
        self,
        find_results: dict[tuple[str, str], list[KnowledgeEdge]] | None = None,
        traverse_results: dict[tuple[str, str], list[list[KnowledgeEdge]]] | None = None,
    ) -> None:
        self._find = find_results or {}
        self._traverse = traverse_results or {}
        self.find_calls: list[dict] = []
        self.traverse_calls: list[dict] = []

    async def find_edges(
        self,
        *,
        source_type=None,
        source_id=None,
        target_type=None,
        target_id=None,
        relation=None,
        limit: int = 100,
    ) -> list[KnowledgeEdge]:
        self.find_calls.append({"source_id": source_id, "target_id": target_id, "limit": limit})
        if source_id is not None:
            return list(self._find.get(("source", source_id), []))[:limit]
        if target_id is not None:
            return list(self._find.get(("target", target_id), []))[:limit]
        return []

    async def traverse(
        self,
        *,
        source_type,
        source_id,
        max_hops: int = 3,
        relation_filter=None,
    ) -> list[list[KnowledgeEdge]]:
        self.traverse_calls.append({"source_id": source_id, "max_hops": max_hops})
        return list(self._traverse.get((source_type.value, source_id), []))


# ── Test 1: late-bind setter ────────────────────────────────────────


def test_attach_knowledge_graph_late_binds() -> None:
    svc = OracleService()
    assert svc._knowledge_graph is None
    g1 = _StubGraph()
    svc.attach_knowledge_graph(g1)
    assert svc._knowledge_graph is g1
    g2 = _StubGraph()
    svc.attach_knowledge_graph(g2)
    assert svc._knowledge_graph is g2  # idempotent / last-write-wins


# ── Test 2: method shape ────────────────────────────────────────────


def test_query_graph_method_shape() -> None:
    svc = OracleService()
    assert inspect.iscoroutinefunction(svc._query_graph)
    sig = inspect.signature(svc._query_graph)
    params = sig.parameters
    assert "query_text" in params
    assert "k" in params
    assert params["k"].kind == inspect.Parameter.KEYWORD_ONLY


# ── Test 3: unattached returns empty ────────────────────────────────


@pytest.mark.asyncio
async def test_query_graph_unattached_returns_empty() -> None:
    svc = OracleService()
    out = await svc._query_graph("alice engine", k=5)
    assert out == []


# ── Test 4: direct match on source_id ───────────────────────────────


@pytest.mark.asyncio
async def test_query_graph_one_hop_direct_match_source() -> None:
    edge = _make_edge(source_id="alice", target_id="bob", weight=0.8, confidence=0.9, edge_id="e1")
    graph = _StubGraph(find_results={("source", "alice"): [edge]})
    svc = OracleService(knowledge_graph=graph)
    out = await svc._query_graph("alice", k=5)
    assert len(out) == 1
    r = out[0]
    assert r.source_tier == "graph"
    assert r.provenance == "[knowledge graph]"
    assert r.score == pytest.approx(0.8 * 0.9 * _GRAPH_HOP_PROXIMITY_DIRECT)
    assert r.metadata["edge_id"] == "e1"
    assert r.metadata["matched_direction"] == "source"


# ── Test 5: direct match on target_id ───────────────────────────────


@pytest.mark.asyncio
async def test_query_graph_one_hop_direct_match_target() -> None:
    edge = _make_edge(source_id="bob", target_id="alice", weight=0.5, confidence=0.6, edge_id="e2")
    graph = _StubGraph(find_results={("target", "alice"): [edge]})
    svc = OracleService(knowledge_graph=graph)
    out = await svc._query_graph("alice", k=5)
    assert len(out) == 1
    assert out[0].metadata["edge_id"] == "e2"
    assert out[0].metadata["matched_direction"] == "target"
    assert out[0].score == pytest.approx(0.5 * 0.6 * _GRAPH_HOP_PROXIMITY_DIRECT)


# ── Test 6: 2-hop with proximity discount ───────────────────────────


@pytest.mark.asyncio
async def test_query_graph_two_hop_with_proximity_discount() -> None:
    a_b = _make_edge(source_id="alice", target_id="bob", weight=1.0, confidence=1.0, edge_id="ab")
    b_c = _make_edge(source_id="bob", target_id="carol", weight=0.5, confidence=0.8, edge_id="bc")
    graph = _StubGraph(
        find_results={("source", "alice"): [a_b]},
        traverse_results={(KnowledgeEntityType.AGENT.value, "bob"): [[b_c]]},
    )
    svc = OracleService(knowledge_graph=graph)
    out = await svc._query_graph("alice", k=10)
    by_id = {r.metadata["edge_id"]: r for r in out}
    assert "ab" in by_id and "bc" in by_id
    assert by_id["ab"].score == pytest.approx(1.0 * 1.0 * _GRAPH_HOP_PROXIMITY_DIRECT)
    assert by_id["bc"].score == pytest.approx(0.5 * 0.8 * _GRAPH_HOP_PROXIMITY_TWO_HOP)


# ── Test 7: dedupe by edge.id keeps highest score ───────────────────


@pytest.mark.asyncio
async def test_query_graph_dedupe_keeps_highest_score() -> None:
    edge = _make_edge(source_id="alice", target_id="alice", weight=0.4, confidence=0.5, edge_id="loop")
    graph = _StubGraph(find_results={("source", "alice"): [edge], ("target", "alice"): [edge]})
    svc = OracleService(knowledge_graph=graph)
    out = await svc._query_graph("alice", k=10)
    assert len(out) == 1
    assert out[0].metadata["edge_id"] == "loop"


# ── Test 8: default active_tiers includes graph ─────────────────────


@pytest.mark.asyncio
async def test_default_active_tiers_includes_graph() -> None:
    svc = OracleService()
    spy = AsyncMock(return_value=[])
    svc._query_graph = spy  # type: ignore[method-assign]
    await svc.query("hello world")
    assert spy.await_count == 1


# ── Test 9: expansion happy path ────────────────────────────────────


@pytest.mark.asyncio
async def test_expand_via_graph_happy_path() -> None:
    parent = OracleResult(
        source_tier="semantic",
        content="alice collaborated with bob",
        score=1.0,
        metadata={},
        provenance="[semantic: doc]",
    )
    edge = _make_edge(source_id="alice", target_id="bob", weight=0.8, confidence=0.9, edge_id="ex1")
    graph = _StubGraph(find_results={("source", "alice"): [edge]})
    svc = OracleService(knowledge_graph=graph)
    out = await svc._expand_via_graph([parent], top_k=5)
    assert len(out) == 1
    r = out[0]
    assert r.provenance == "[graph expansion: [semantic: doc]]"
    assert r.score == pytest.approx(1.0 * _GRAPH_EXPANSION_DISCOUNT * 0.8 * 0.9)
    assert r.metadata["expansion_source"] == "[semantic: doc]"
    assert r.metadata["expansion_parent_tier"] == "semantic"


# ── Test 10: expansion skips graph parents ──────────────────────────


@pytest.mark.asyncio
async def test_expand_via_graph_skips_graph_parents() -> None:
    edge = _make_edge(source_id="alice", target_id="bob", edge_id="exg")
    graph = _StubGraph(find_results={("source", "alice"): [edge]})
    svc = OracleService(knowledge_graph=graph)
    graph_parent = OracleResult(
        source_tier="graph",
        content="alice collaborated with carol",
        score=0.9,
        metadata={},
        provenance="[knowledge graph]",
    )
    out = await svc._expand_via_graph([graph_parent], top_k=5)
    assert out == []


# ── Test 11: respects top_k and per-parent cap ──────────────────────


@pytest.mark.asyncio
async def test_expand_via_graph_respects_top_k_and_per_parent_cap() -> None:
    # 10 parents, each with content "alpha"; graph returns 20 candidate edges
    # (call site limits to _GRAPH_EXPANSION_PER_PARENT via find_edges limit).
    edges = [
        _make_edge(source_id="alpha", target_id=f"t{i}", edge_id=f"e{i}")
        for i in range(20)
    ]
    graph = _StubGraph(find_results={("source", "alpha"): edges})
    svc = OracleService(knowledge_graph=graph)
    parents = [
        OracleResult(
            source_tier="semantic",
            content="alpha mentions everywhere",
            score=1.0 - i * 0.01,
            metadata={},
            provenance=f"[semantic: p{i}]",
        )
        for i in range(10)
    ]
    out = await svc._expand_via_graph(parents, top_k=3)
    # Per-parent cap of 5; 3 parents; first parent consumes all 5 unique edges,
    # remaining parents see them in seen_edges → emit 0.
    assert len(out) == _GRAPH_EXPANSION_PER_PARENT
    assert all(r.metadata["expansion_parent_tier"] == "semantic" for r in out)


# ── Test 12: runtime late-bind smoke (helper attach block) ──────────


def test_runtime_attaches_knowledge_graph_to_oracle() -> None:
    svc = OracleService()
    edges = SimpleNamespace()  # opaque token; attach is just assignment
    rt = SimpleNamespace(_oracle_service=svc, knowledge_edges=edges)
    if rt._oracle_service is not None and rt.knowledge_edges is not None:
        rt._oracle_service.attach_knowledge_graph(rt.knowledge_edges)
    assert svc._knowledge_graph is edges


# ── Test 13: token extractor behavior ───────────────────────────────


def test_extract_entity_tokens_basics() -> None:
    # Drops short, drops stopwords, strips punct, dedupes, caps at 16
    out = _extract_entity_tokens("The Alice and Bob, Alice! collaborated with engine.")
    assert "alice" in out
    assert "bob" in out
    assert "engine" in out
    assert "the" not in out
    assert "and" not in out
    # "with" is in the stopword set
    assert "with" not in out
    # dedupe
    assert out.count("alice") == 1
    # Empty / None
    assert _extract_entity_tokens("") == []
    # Cap at 16
    long_text = " ".join(f"tok{i:02d}" for i in range(30))
    assert len(_extract_entity_tokens(long_text)) == 16
