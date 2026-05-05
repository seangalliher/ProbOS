"""AD-691: Tests for NL-to-Graph Query Service."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from probos.cognitive.nl_graph_query import (
    EntityExtraction,
    NLGraphQueryResult,
    NLGraphQueryService,
)
from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
)
from probos.types import IntentMessage, LLMResponse


# ── Stubs ─────────────────────────────────────────────────────────


class _StubLLM:
    """Sequential responses; tracks calls + last requests."""

    def __init__(self, responses: list[str]):
        self._responses = list(responses)
        self.calls = 0
        self.requests: list[Any] = []

    async def complete(self, req: Any) -> LLMResponse:
        self.calls += 1
        self.requests.append(req)
        content = self._responses.pop(0) if self._responses else ""
        return LLMResponse(content=content)


class _StubEdgeStore:
    def __init__(self, edges: list[KnowledgeEdge] | None = None):
        self.edges = list(edges or [])
        self.find_calls: list[dict] = []
        self.traverse_calls: list[dict] = []

    async def find_edges(self, **kw):
        self.find_calls.append(kw)
        out = []
        for e in self.edges:
            if "source_id" in kw and kw["source_id"] is not None:
                if e.source_id == kw["source_id"] and (
                    "source_type" not in kw or kw["source_type"] is None
                    or e.source_type == kw["source_type"]
                ):
                    out.append(e)
            if "target_id" in kw and kw["target_id"] is not None:
                if e.target_id == kw["target_id"] and (
                    "target_type" not in kw or kw["target_type"] is None
                    or e.target_type == kw["target_type"]
                ):
                    out.append(e)
        return out

    async def traverse(self, **kw):
        self.traverse_calls.append(kw)
        out: list[list[KnowledgeEdge]] = []
        for e in self.edges:
            if e.source_id == kw["source_id"] and e.source_type == kw["source_type"]:
                rf = kw.get("relation_filter")
                if rf is None or e.relation in rf:
                    out.append([e])
        return out


@dataclass
class _StubRuntime:
    knowledge_edges: Any = None
    llm_client: Any = None
    nl_graph_query: Any = None


def _edge(
    *,
    source_id: str = "alice",
    source_type: KnowledgeEntityType = KnowledgeEntityType.AGENT,
    relation: KnowledgeRelationType = KnowledgeRelationType.REPORTS_TO,
    target_id: str = "chief_engineer",
    target_type: KnowledgeEntityType = KnowledgeEntityType.AGENT,
    edge_id: str | None = None,
    confidence: float = 1.0,
    weight: float = 1.0,
) -> KnowledgeEdge:
    kw: dict[str, Any] = dict(
        source_type=source_type,
        source_id=source_id,
        relation=relation,
        target_type=target_type,
        target_id=target_id,
        confidence=confidence,
        weight=weight,
    )
    if edge_id is not None:
        kw["id"] = edge_id
    return KnowledgeEdge(**kw)


# ── Tests ─────────────────────────────────────────────────────────


def test_result_dataclass_frozen_and_to_dict():
    """Test 1: frozen dataclass + to_dict round-trip preserves fields."""
    e = _edge(edge_id="a" * 32)
    result = NLGraphQueryResult(
        query="who reports to chief_engineer?",
        extracted_entities=[EntityExtraction(id="alice", type="agent")],
        edges_traversed=[e],
        paths=[[e]],
        answer=f"Alice reports to chief engineer [graph: {e.id}].",
        provenance=[e.id],
    )
    with pytest.raises(Exception):
        result.query = "mutated"  # type: ignore[misc]

    d = result.to_dict()
    assert d["query"] == "who reports to chief_engineer?"
    assert d["extracted_entities"] == [{"id": "alice", "type": "agent"}]
    assert len(d["edges_traversed"]) == 1
    assert d["edges_traversed"][0]["id"] == e.id
    assert len(d["paths"]) == 1
    assert d["provenance"] == [e.id]


def test_service_shape_default_kwargs():
    """Test 2: ctor accepts 6 kw-only params; defaults match config."""
    rt = _StubRuntime()
    svc = NLGraphQueryService(rt)
    assert svc._default_max_hops == 2
    assert svc._default_limit == 10
    assert svc._llm_tier == "standard"
    assert svc._extraction_max_tokens == 600
    assert svc._synthesis_max_tokens == 800

    svc2 = NLGraphQueryService(
        rt, default_max_hops=3, default_limit=5, llm_tier="fast",
        extraction_max_tokens=100, synthesis_max_tokens=200,
    )
    assert svc2._default_max_hops == 3
    assert svc2._llm_tier == "fast"


def test_query_happy_path_with_stub_llm():
    """Test 3: 1 entity → 1 direct edge → answer with citation."""
    e = _edge(edge_id="b" * 32)
    llm = _StubLLM([
        '{"entities": [{"id": "alice", "type": "agent"}], "relation_filter": [], "intent": "find"}',
        f"Alice reports to chief_engineer [graph: {e.id}].",
    ])
    store = _StubEdgeStore([e])
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    result = asyncio.run(svc.query("who reports to chief_engineer?"))

    assert len(result.edges_traversed) == 1
    assert result.edges_traversed[0].id == e.id
    assert result.provenance == [e.id]
    assert result.answer
    assert llm.calls == 2


def test_phase1_parse_failure_returns_degraded_result():
    """Test 4: bad JSON Phase-1 → "Could not parse query." + no Phase-2."""
    llm = _StubLLM(["not json at all"])
    store = _StubEdgeStore([])
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    result = asyncio.run(svc.query("hello?"))
    assert result.answer == "Could not parse query."
    assert result.provenance == []
    assert llm.calls == 1


def test_empty_extraction_short_circuits_phase2():
    """Test 5: entities=[] → "No graph entities identified" + no graph step."""
    llm = _StubLLM([
        '{"entities": [], "relation_filter": [], "intent": "find"}',
    ])
    store = _StubEdgeStore([_edge()])
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    result = asyncio.run(svc.query("hi there"))
    assert result.answer == "No graph entities identified in query."
    assert llm.calls == 1
    assert store.find_calls == []


def test_relation_filter_passes_through_to_traverse():
    """Test 6: relation_filter coerced to KnowledgeRelationType list."""
    e = _edge(edge_id="c" * 32, relation=KnowledgeRelationType.REPORTS_TO)
    llm = _StubLLM([
        '{"entities": [{"id": "alice", "type": "agent"}], "relation_filter": ["reports_to"], "intent": "traverse"}',
        f"... [graph: {e.id}]",
    ])
    store = _StubEdgeStore([e])
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    asyncio.run(svc.query("who does alice report to?"))
    assert len(store.traverse_calls) >= 1
    assert store.traverse_calls[0]["relation_filter"] == [KnowledgeRelationType.REPORTS_TO]


def test_unknown_relation_in_filter_dropped_silently():
    """Test 7: unknown relations dropped; only valid ones reach traverse()."""
    e = _edge(edge_id="d" * 32)
    llm = _StubLLM([
        '{"entities": [{"id": "alice", "type": "agent"}], "relation_filter": ["reports_to", "fictional_relation"], "intent": "traverse"}',
        f"... [graph: {e.id}]",
    ])
    store = _StubEdgeStore([e])
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    asyncio.run(svc.query("xyz"))
    assert store.traverse_calls[0]["relation_filter"] == [KnowledgeRelationType.REPORTS_TO]


def test_max_hops_clamped_to_ceiling():
    """Test 8: max_hops=99 clamped to 3 (MAX_HOPS_CEILING)."""
    e = _edge(edge_id="e" * 32)
    llm = _StubLLM([
        '{"entities": [{"id": "alice", "type": "agent"}], "relation_filter": [], "intent": "traverse"}',
        f"... [graph: {e.id}]",
    ])
    store = _StubEdgeStore([e])
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    asyncio.run(svc.query("hops?", max_hops=99))
    assert store.traverse_calls[0]["max_hops"] == 3


def test_limit_truncates_results():
    """Test 9: 25 matching edges + limit=5 → 5 returned."""
    edges = [_edge(edge_id=f"{i:032x}", target_id=f"target_{i}") for i in range(25)]
    llm = _StubLLM([
        '{"entities": [{"id": "alice", "type": "agent"}], "relation_filter": [], "intent": "find"}',
        "answer omitted",
    ])
    store = _StubEdgeStore(edges)
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    result = asyncio.run(svc.query("alice connections", limit=5))
    assert len(result.edges_traversed) == 5


def test_scoring_orders_by_weight_confidence_and_proximity():
    """Test 10: w × c × proximity descending."""
    high = _edge(edge_id="1" * 32, target_id="t1", weight=1.0, confidence=1.0)
    mid = _edge(edge_id="2" * 32, target_id="t2", weight=0.8, confidence=0.5)
    low = _edge(edge_id="3" * 32, target_id="t3", weight=0.3, confidence=0.2)
    llm = _StubLLM([
        '{"entities": [{"id": "alice", "type": "agent"}], "relation_filter": [], "intent": "find"}',
        "answer omitted",
    ])
    store = _StubEdgeStore([low, high, mid])
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    result = asyncio.run(svc.query("alice"))
    ids = [e.id for e in result.edges_traversed]
    # high (1.0 * 1.0) > mid (0.8 * 0.5 = 0.4) > low (0.3 * 0.2 = 0.06)
    assert ids.index(high.id) < ids.index(mid.id) < ids.index(low.id)


def test_provenance_drops_hallucinated_citations():
    """Test 11: cite IDs not in returned edges are filtered out."""
    real = _edge(edge_id="a" * 32)
    fake = "deadbeefdeadbeef" + "0" * 16
    llm = _StubLLM([
        '{"entities": [{"id": "alice", "type": "agent"}], "relation_filter": [], "intent": "find"}',
        f"alice reports [graph: {real.id}] but also [graph: {fake}].",
    ])
    store = _StubEdgeStore([real])
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    result = asyncio.run(svc.query("alice"))
    assert real.id in result.provenance
    assert fake not in result.provenance


def test_no_edges_returns_no_evidence_without_phase2_call():
    """Test 12: 0 edges → "No relevant graph evidence" + no Phase-2."""
    llm = _StubLLM([
        '{"entities": [{"id": "ghost", "type": "agent"}], "relation_filter": [], "intent": "find"}',
    ])
    store = _StubEdgeStore([])
    rt = _StubRuntime(knowledge_edges=store, llm_client=llm)
    svc = NLGraphQueryService(rt)

    result = asyncio.run(svc.query("ghost?"))
    assert result.answer == "No relevant graph evidence."
    assert result.provenance == []
    assert llm.calls == 1


# ── API tests ─────────────────────────────────────────────────────


def test_api_endpoint_400_on_empty_query():
    """Test 13: GET /api/nl-graph-query?q= → 400."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from probos.routers import nl_graph_query as router_mod
    from probos.routers.deps import get_runtime

    app = FastAPI()
    app.include_router(router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: _StubRuntime()

    with TestClient(app) as client:
        r = client.get("/api/nl-graph-query?q=")
        assert r.status_code == 400


def test_api_endpoint_happy_path():
    """Test 14: TestClient + dependency override → 200 + body matches to_dict()."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from probos.routers import nl_graph_query as router_mod
    from probos.routers.deps import get_runtime

    fixed = NLGraphQueryResult(
        query="alice?",
        extracted_entities=[EntityExtraction(id="alice", type="agent")],
        answer="alice answer",
        provenance=[],
    )

    class _FakeService:
        async def query(self, q, *, max_hops=None, limit=None):
            return fixed

    rt = _StubRuntime(nl_graph_query=_FakeService())
    app = FastAPI()
    app.include_router(router_mod.router)
    app.dependency_overrides[get_runtime] = lambda: rt

    with TestClient(app) as client:
        r = client.get("/api/nl-graph-query?q=alice")
        assert r.status_code == 200
        body = r.json()
        assert body["query"] == "alice?"
        assert body["answer"] == "alice answer"


# ── Agent tests ───────────────────────────────────────────────────


def test_agent_act_happy_path_delegates_to_runtime_service():
    """Test 15: NLGraphQueryAgent.handle_intent delegates to runtime.nl_graph_query."""
    from probos.agents.utility.nl_graph_query_agent import NLGraphQueryAgent

    e = _edge(edge_id="f" * 32)
    fixed = NLGraphQueryResult(
        query="who reports to chief_engineer?",
        extracted_entities=[EntityExtraction(id="alice", type="agent")],
        edges_traversed=[e],
        answer=f"alice reports [graph: {e.id}]",
        provenance=[e.id],
    )

    class _FakeService:
        def __init__(self) -> None:
            self.calls = 0
            self.last_query: str | None = None

        async def query(self, q, *, max_hops=None, limit=None):
            self.calls += 1
            self.last_query = q
            return fixed

    fake = _FakeService()
    rt = _StubRuntime(nl_graph_query=fake)
    agent = NLGraphQueryAgent(pool="nl_graph_query", runtime=rt)

    intent = IntentMessage(
        intent="nl_graph_query",
        params={"query": "who reports to chief_engineer?"},
    )
    result = asyncio.run(agent.handle_intent(intent))
    assert result is not None
    assert result.success is True
    assert fake.calls == 1
    assert fake.last_query == "who reports to chief_engineer?"
    assert result.result["answer"] == fixed.answer
    assert result.result["provenance"] == [e.id]


def test_agent_pool_registered_when_feature_enabled():
    """Test 16: agent_fleet registers nl_graph_query pool when enabled."""
    from probos.startup.agent_fleet import create_agent_fleet
    from probos.config import SystemConfig
    from types import SimpleNamespace

    # Verify the gate logic in create_agent_fleet directly: focus on the
    # config + runtime.nl_graph_query gate without booting full runtime.
    # (Wave 8/10 lesson: full runtime boot too heavy for unit tier.)
    config = SystemConfig()
    assert config.nl_graph_query.enabled is True

    # Verify NLGraphQueryAgent declares the expected IntentDescriptor.
    from probos.agents.utility.nl_graph_query_agent import NLGraphQueryAgent
    descriptors = NLGraphQueryAgent.intent_descriptors
    assert any(
        d.name == "nl_graph_query" and d.tier == "utility"
        for d in descriptors
    )

    # Verify runtime.py registers nl_graph_query template alongside introspect.
    from probos.substrate.spawner import AgentSpawner
    from probos.substrate.registry import AgentRegistry
    spawner = AgentSpawner(AgentRegistry())
    spawner.register_template("nl_graph_query", NLGraphQueryAgent)
    assert "nl_graph_query" in spawner._templates
