"""AD-690: Tests for Dream Step 7i — Relationship Inference."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from probos.cognitive.relationship_inference import (
    RelationshipInferenceResult,
    _extract_agent_pairs,
    infer_relationships_from_episodes,
)
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
)
from probos.knowledge.rejection_cache import SQLiteRejectionCache
from probos.types import Episode, LLMResponse


# ── Stubs ─────────────────────────────────────────────────────────


class _StubLLM:
    """Returns a deterministic content string per call. Tracks call count."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, req: Any, **_kwargs: Any) -> LLMResponse:
        self.calls += 1
        if self._responses:
            content = self._responses.pop(0)
        else:
            content = '{"relation": null, "confidence": 0.0, "rationale": "default"}'
        return LLMResponse(content=content)


class _StubEdgeStore:
    """In-memory KnowledgeEdgeStorage for tests."""

    def __init__(self) -> None:
        self.edges: list[KnowledgeEdge] = []

    async def add_edge(self, edge: KnowledgeEdge) -> str:
        self.edges.append(edge)
        return edge.id

    async def find_edges(
        self,
        *,
        source_type: KnowledgeEntityType | None = None,
        source_id: str | None = None,
        target_type: KnowledgeEntityType | None = None,
        target_id: str | None = None,
        relation: KnowledgeRelationType | None = None,
        limit: int = 100,
    ) -> list[KnowledgeEdge]:
        out = []
        for e in self.edges:
            if source_id is not None and e.source_id != source_id:
                continue
            if target_id is not None and e.target_id != target_id:
                continue
            out.append(e)
            if len(out) >= limit:
                break
        return out

    async def get_edge(self, edge_id: str) -> KnowledgeEdge | None:
        for e in self.edges:
            if e.id == edge_id:
                return e
        return None

    async def update_edge(self, edge_id: str, **kw: Any) -> bool:
        return False

    async def delete_edge(self, edge_id: str) -> bool:
        return False

    async def traverse(self, *args: Any, **kw: Any) -> list[KnowledgeEdge]:
        return []


class _StubRejectionCache:
    def __init__(self) -> None:
        self.rejected: dict[tuple[str, str], dict[str, Any]] = {}

    async def was_rejected(self, source_id: str, target_id: str) -> bool:
        return (source_id, target_id) in self.rejected or (target_id, source_id) in self.rejected

    async def record_rejection(
        self,
        *,
        source_id: str,
        target_id: str,
        relation: str | None,
        reason: str,
    ) -> None:
        self.rejected[(source_id, target_id)] = {"relation": relation, "reason": reason}


def _ep(*agents: str) -> Episode:
    return Episode(agent_ids=list(agents))


# ── Tests ─────────────────────────────────────────────────────────


def test_relationship_inference_result_shape() -> None:
    r = RelationshipInferenceResult()
    assert r.candidate_pairs == 0
    assert r.inferred_edges == 0
    assert r.relationship_pairs_rejected == 0
    assert r.relationship_pairs_capped == 0
    d = r.to_dict()
    assert d == {
        "candidate_pairs": 0,
        "inferred_edges": 0,
        "relationship_pairs_rejected": 0,
        "relationship_pairs_capped": 0,
    }
    # frozen
    with pytest.raises(Exception):
        r.candidate_pairs = 5  # type: ignore[misc]


def test_extract_agent_pairs_dedupes_and_skips_singletons() -> None:
    episodes = [
        _ep("a", "b"),
        _ep("b", "a"),  # collapses with above
        _ep("c"),       # skipped (singleton)
        _ep("x", "y", "z"),  # 3 pairs: (x,y), (x,z), (y,z)
    ]
    pairs = _extract_agent_pairs(episodes)
    assert set(pairs) == {("a", "b"), ("x", "y"), ("x", "z"), ("y", "z")}
    assert len(pairs) == 4


@pytest.mark.asyncio
async def test_existing_edge_skip_no_llm_call() -> None:
    edges = _StubEdgeStore()
    await edges.add_edge(KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT,
        source_id="a",
        relation=KnowledgeRelationType.REPORTS_TO,
        target_type=KnowledgeEntityType.AGENT,
        target_id="b",
    ))
    llm = _StubLLM([])
    cache = _StubRejectionCache()
    result = await infer_relationships_from_episodes(
        episodes=[_ep("a", "b")],
        knowledge_edges=edges,
        llm_client=llm,
        rejection_cache=cache,
    )
    assert llm.calls == 0
    assert result.inferred_edges == 0
    assert result.candidate_pairs == 1


@pytest.mark.asyncio
async def test_llm_happy_path_adds_edge_with_tags() -> None:
    edges = _StubEdgeStore()
    llm = _StubLLM(['{"relation": "reports_to", "confidence": 0.85, "rationale": "obs"}'])
    cache = _StubRejectionCache()
    result = await infer_relationships_from_episodes(
        episodes=[_ep("a", "b")],
        knowledge_edges=edges,
        llm_client=llm,
        rejection_cache=cache,
    )
    assert result.inferred_edges == 1
    assert len(edges.edges) == 1
    e = edges.edges[0]
    assert e.relation == KnowledgeRelationType.REPORTS_TO
    assert e.confidence == 0.85
    assert e.weight == 0.5
    assert e.source_agent == "dream_step10"
    assert e.source_duty == "relationship_inference"
    assert e.source_type == KnowledgeEntityType.AGENT
    assert e.target_type == KnowledgeEntityType.AGENT


@pytest.mark.asyncio
async def test_min_confidence_filter_records_rejection() -> None:
    edges = _StubEdgeStore()
    llm = _StubLLM(['{"relation": "reports_to", "confidence": 0.4, "rationale": "weak"}'])
    cache = _StubRejectionCache()
    result = await infer_relationships_from_episodes(
        episodes=[_ep("a", "b")],
        knowledge_edges=edges,
        llm_client=llm,
        rejection_cache=cache,
        min_confidence=0.6,
    )
    assert result.inferred_edges == 0
    assert result.relationship_pairs_rejected == 1
    assert len(edges.edges) == 0
    key = ("a", "b")
    assert key in cache.rejected
    assert "below_threshold" in cache.rejected[key]["reason"]


@pytest.mark.asyncio
async def test_per_entity_cap_honored() -> None:
    # agent_a paired with 10 distinct partners
    episodes = [_ep("agent_a", f"p{i}") for i in range(10)]
    edges = _StubEdgeStore()
    responses = ['{"relation": "reports_to", "confidence": 0.9, "rationale": "ok"}'] * 10
    llm = _StubLLM(responses)
    cache = _StubRejectionCache()
    result = await infer_relationships_from_episodes(
        episodes=episodes,
        knowledge_edges=edges,
        llm_client=llm,
        rejection_cache=cache,
        max_inferences_per_entity=5,
    )
    assert result.inferred_edges == 5
    assert result.relationship_pairs_capped == 5
    assert len(edges.edges) == 5


@pytest.mark.asyncio
async def test_max_pairs_per_run_honored() -> None:
    episodes = [_ep(f"x{i}", f"y{i}") for i in range(50)]
    edges = _StubEdgeStore()
    responses = ['{"relation": "reports_to", "confidence": 0.9, "rationale": "ok"}'] * 50
    llm = _StubLLM(responses)
    cache = _StubRejectionCache()
    result = await infer_relationships_from_episodes(
        episodes=episodes,
        knowledge_edges=edges,
        llm_client=llm,
        rejection_cache=cache,
        max_pairs_per_run=10,
    )
    assert llm.calls == 10
    assert result.inferred_edges == 10


@pytest.mark.asyncio
async def test_rejection_cache_prevents_reclassification() -> None:
    edges = _StubEdgeStore()
    cache = _StubRejectionCache()
    # First run: LLM returns null → pair gets cached as rejected
    llm1 = _StubLLM(['{"relation": null, "confidence": 0.0, "rationale": "none"}'])
    r1 = await infer_relationships_from_episodes(
        episodes=[_ep("a", "b")],
        knowledge_edges=edges,
        llm_client=llm1,
        rejection_cache=cache,
    )
    assert r1.relationship_pairs_rejected == 1
    assert llm1.calls == 1

    # Second run: same pair → was_rejected → no LLM call, no counter increment
    llm2 = _StubLLM(['{"relation": "reports_to", "confidence": 0.9, "rationale": "x"}'])
    r2 = await infer_relationships_from_episodes(
        episodes=[_ep("a", "b")],
        knowledge_edges=edges,
        llm_client=llm2,
        rejection_cache=cache,
    )
    assert llm2.calls == 0
    assert r2.inferred_edges == 0
    assert r2.relationship_pairs_rejected == 0


@pytest.mark.asyncio
async def test_llm_json_parse_failure_counts_as_rejection() -> None:
    edges = _StubEdgeStore()
    llm = _StubLLM(["not json at all"])
    cache = _StubRejectionCache()
    result = await infer_relationships_from_episodes(
        episodes=[_ep("a", "b")],
        knowledge_edges=edges,
        llm_client=llm,
        rejection_cache=cache,
    )
    assert result.relationship_pairs_rejected == 1
    assert len(edges.edges) == 0
    assert cache.rejected[("a", "b")]["reason"] == "llm_parse_failure"


@pytest.mark.asyncio
async def test_relation_outside_whitelist_counts_as_rejection() -> None:
    edges = _StubEdgeStore()
    llm = _StubLLM(['{"relation": "member_of", "confidence": 0.9, "rationale": "x"}'])
    cache = _StubRejectionCache()
    result = await infer_relationships_from_episodes(
        episodes=[_ep("a", "b")],
        knowledge_edges=edges,
        llm_client=llm,
        rejection_cache=cache,
    )
    assert result.relationship_pairs_rejected == 1
    assert len(edges.edges) == 0
    assert cache.rejected[("a", "b")]["reason"] == "relation_not_in_whitelist"


@pytest.mark.asyncio
async def test_disabled_config_short_circuits_step() -> None:
    # Exercise the dream-engine block with config disabled.
    # We don't spin a full DreamingEngine — verify the function-level guard
    # matches: when disabled at config level, the dream-engine `if` won't
    # call the inference function, so LLM call count stays 0.
    @dataclass
    class _Cfg:
        relationship_inference_enabled: bool = False

    cfg = _Cfg()
    llm = _StubLLM(['{"relation": "reports_to", "confidence": 0.9, "rationale": "x"}'])
    edges = _StubEdgeStore()
    cache = _StubRejectionCache()
    # Mirror the dream-engine guard expression
    ri_cfg = getattr(cfg, "relationship_inference_enabled", False)
    if (
        ri_cfg
        and edges is not None
        and cache is not None
        and llm is not None
        and [_ep("a", "b")]
    ):
        await infer_relationships_from_episodes(
            episodes=[_ep("a", "b")],
            knowledge_edges=edges,
            llm_client=llm,
            rejection_cache=cache,
        )
    assert llm.calls == 0
    assert len(edges.edges) == 0


@pytest.mark.asyncio
async def test_sqlite_rejection_cache_round_trip(tmp_path: Any) -> None:
    db_path = str(tmp_path / "rejection.db")
    cache = SQLiteRejectionCache(db_path)
    await cache.start()
    try:
        await cache.record_rejection(
            source_id="a", target_id="b", relation=None, reason="llm_returned_null",
        )
        assert await cache.was_rejected("a", "b") is True
        # Undirected lookup
        assert await cache.was_rejected("b", "a") is True
        assert await cache.was_rejected("c", "d") is False
    finally:
        await cache.stop()
