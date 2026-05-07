"""AD-520: Tests for GET /api/ontology/graph."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pytest
from unittest.mock import MagicMock

from probos.knowledge.edges import (
    KnowledgeEdge,
    KnowledgeEntityType,
    KnowledgeRelationType,
)
from probos.routers.ontology import get_ontology_graph


@dataclass
class _FakeDept:
    id: str
    name: str
    description: str = ""


@dataclass
class _FakeAssignment:
    agent_type: str
    post_id: str
    callsign: str = ""
    watches: list[str] = field(default_factory=list)
    agent_id: str | None = None


class _FakeOntology:
    def __init__(self, depts: list[_FakeDept], manifest: list[dict[str, Any]], assignments: list[_FakeAssignment]):
        self._depts = depts
        self._manifest = manifest
        self._assignments = assignments

    def get_departments(self) -> list[_FakeDept]:
        return self._depts

    def get_crew_manifest(self, *, trust_network: Any = None, callsign_registry: Any = None) -> list[dict[str, Any]]:
        return self._manifest

    def get_all_assignments(self) -> list[_FakeAssignment]:
        return self._assignments


def _make_runtime(*, ontology: Any = None, knowledge_edges: Any = None) -> Any:
    rt = MagicMock()
    rt.ontology = ontology
    rt.knowledge_edges = knowledge_edges
    rt.trust_network = None
    rt.callsign_registry = None
    return rt


def _sample_manifest_and_assignments():
    manifest = [
        {"agent_type": "scout", "agent_id": "scout-1", "callsign": "Scout", "department": "science", "rank": "ensign", "post": "scout", "trust": 0.8, "on_watch": True},
    ]
    assignments = [_FakeAssignment(agent_type="scout", post_id="scout-post", callsign="Scout", agent_id="scout-1")]
    return manifest, assignments


@pytest.mark.asyncio
async def test_graph_returns_503_when_ontology_missing() -> None:
    rt = _make_runtime(ontology=None)
    res = await get_ontology_graph(runtime=rt)
    assert getattr(res, "status_code", 200) == 503


@pytest.mark.asyncio
async def test_graph_happy_path_returns_nodes_and_member_of_edges() -> None:
    manifest, assignments = _sample_manifest_and_assignments()
    ont = _FakeOntology([_FakeDept(id="science", name="Science")], manifest, assignments)
    rt = _make_runtime(ontology=ont)
    res = await get_ontology_graph(runtime=rt)
    assert isinstance(res, dict)
    assert "nodes" in res and "edges" in res and "generated_at" in res
    # 1 department + 1 agent
    assert len(res["nodes"]) == 2
    assert any(n["type"] == "department" and n["id"] == "science" for n in res["nodes"])
    assert any(n["type"] == "agent" and n["id"] == "scout-1" for n in res["nodes"])
    # 1 member_of edge from assignment
    member_edges = [e for e in res["edges"] if e["relation"] == "member_of"]
    assert len(member_edges) == 1
    assert member_edges[0]["source"] == "scout"
    assert member_edges[0]["target"] == "scout-post"


@pytest.mark.asyncio
async def test_graph_include_edges_merges_knowledge_edges() -> None:
    manifest, assignments = _sample_manifest_and_assignments()
    ont = _FakeOntology([_FakeDept(id="science", name="Science")], manifest, assignments)
    edge = KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT,
        source_id="scout",
        relation=KnowledgeRelationType.REPORTS_TO,
        target_type=KnowledgeEntityType.AGENT,
        target_id="captain",
    )

    class _KE:
        async def find_edges(self, *, limit: int = 100) -> list[KnowledgeEdge]:
            assert limit == 250
            return [edge]

    rt = _make_runtime(ontology=ont, knowledge_edges=_KE())
    res = await get_ontology_graph(runtime=rt, include_edges=True, max_edges=250)
    relations = {e["relation"] for e in res["edges"]}
    assert "member_of" in relations
    assert "reports_to" in relations


@pytest.mark.asyncio
async def test_graph_edge_relations_filter_applied() -> None:
    manifest, assignments = _sample_manifest_and_assignments()
    ont = _FakeOntology([_FakeDept(id="science", name="Science")], manifest, assignments)
    e1 = KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT, source_id="a",
        relation=KnowledgeRelationType.REPORTS_TO,
        target_type=KnowledgeEntityType.AGENT, target_id="b",
    )
    e2 = KnowledgeEdge(
        source_type=KnowledgeEntityType.AGENT, source_id="a",
        relation=KnowledgeRelationType.COMPETENT_IN,
        target_type=KnowledgeEntityType.CAPABILITY, target_id="c",
    )

    class _KE:
        async def find_edges(self, *, limit: int = 100) -> list[KnowledgeEdge]:
            return [e1, e2]

    rt = _make_runtime(ontology=ont, knowledge_edges=_KE())
    res = await get_ontology_graph(runtime=rt, edge_relations="reports_to,member_of")
    knowledge_relations = {e["relation"] for e in res["edges"] if "id" in e and not e["id"].startswith("member_of:")}
    # Only reports_to should pass filter
    assert "reports_to" in knowledge_relations
    assert "competent_in" not in knowledge_relations


@pytest.mark.asyncio
async def test_graph_find_edges_failure_logs_warning_and_continues(caplog: pytest.LogCaptureFixture) -> None:
    manifest, assignments = _sample_manifest_and_assignments()
    ont = _FakeOntology([_FakeDept(id="science", name="Science")], manifest, assignments)

    class _KE:
        async def find_edges(self, *, limit: int = 100) -> list[KnowledgeEdge]:
            raise RuntimeError("boom")

    rt = _make_runtime(ontology=ont, knowledge_edges=_KE())
    with caplog.at_level(logging.WARNING, logger="probos.routers.ontology"):
        res = await get_ontology_graph(runtime=rt)
    # assignment-derived member_of edge still present
    assert any(e["relation"] == "member_of" for e in res["edges"])
    assert any("find_edges failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_graph_max_nodes_truncates_combined_node_list() -> None:
    depts = [_FakeDept(id=f"d{i}", name=f"D{i}") for i in range(8)]
    manifest = [
        {"agent_type": f"a{i}", "agent_id": f"a{i}", "department": "d0", "rank": "ensign", "post": "p", "trust": 0.5, "on_watch": False}
        for i in range(8)
    ]
    assignments = [_FakeAssignment(agent_type=f"a{i}", post_id="p", agent_id=f"a{i}") for i in range(8)]
    ont = _FakeOntology(depts, manifest, assignments)
    rt = _make_runtime(ontology=ont)
    res = await get_ontology_graph(runtime=rt, max_nodes=5)
    assert len(res["nodes"]) == 5
