"""AD-694a: direct unit tests for ``build_ontology_graph_snapshot``.

The route handler in ``probos.routers.ontology`` already has integration
tests via ``test_ad520_graph_endpoint``. These tests exercise the
extracted builder directly with stub ontology objects — no FastAPI
dependency, no runtime construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from probos.ontology.graph_snapshot import build_ontology_graph_snapshot


@dataclass
class _Dept:
    id: str
    name: str
    accent_color: str = "#666680"


@dataclass
class _Post:
    id: str
    department_id: str
    reports_to: str = ""


@dataclass
class _Assignment:
    agent_type: str
    post_id: str
    agent_id: str = ""


class _StubOntology:
    def __init__(
        self,
        *,
        departments: list[_Dept],
        posts: list[_Post],
        assignments: list[_Assignment],
        manifest: list[dict[str, Any]],
    ) -> None:
        self._departments = departments
        self._posts = posts
        self._assignments = assignments
        self._manifest = manifest

    def get_departments(self) -> list[_Dept]:
        return list(self._departments)

    def get_posts(self) -> list[_Post]:
        return list(self._posts)

    def get_all_assignments(self) -> list[_Assignment]:
        return list(self._assignments)

    def get_crew_manifest(
        self, *, trust_network: Any = None, callsign_registry: Any = None
    ) -> list[dict[str, Any]]:
        return list(self._manifest)


def _basic_ontology() -> _StubOntology:
    return _StubOntology(
        departments=[
            _Dept(id="science", name="Science"),
            _Dept(id="bridge", name="Bridge"),
        ],
        posts=[
            _Post(id="captain", department_id="bridge"),
            _Post(id="first_officer", department_id="bridge", reports_to="captain"),
            _Post(id="chief_science", department_id="science", reports_to="first_officer"),
            _Post(id="science_officer", department_id="science", reports_to="chief_science"),
        ],
        assignments=[
            _Assignment(agent_type="captain", post_id="captain", agent_id="cap-1"),
            _Assignment(agent_type="architect", post_id="first_officer", agent_id="arch-1"),
            # chief_science is unfilled — used to test reports_to walking
            _Assignment(agent_type="science_officer", post_id="science_officer", agent_id="sci-1"),
        ],
        manifest=[
            {"agent_id": "cap-1", "agent_type": "captain", "department": "bridge", "rank": "captain", "trust": 0.9, "post": "captain"},
            {"agent_id": "arch-1", "agent_type": "architect", "department": "bridge", "rank": "commander", "trust": 0.8, "post": "first_officer"},
            {"agent_id": "sci-1", "agent_type": "science_officer", "department": "science", "rank": "lieutenant", "trust": 0.6, "post": "science_officer"},
        ],
    )


@pytest.mark.asyncio
async def test_snapshot_emits_department_and_agent_nodes() -> None:
    snap = await build_ontology_graph_snapshot(ontology=_basic_ontology())
    types = {n["id"]: n["type"] for n in snap["nodes"]}
    assert types["science"] == "department"
    assert types["bridge"] == "department"
    assert types["sci-1"] == "agent"
    assert types["arch-1"] == "agent"
    assert types["cap-1"] == "agent"


@pytest.mark.asyncio
async def test_member_of_edges_use_agent_instance_ids() -> None:
    snap = await build_ontology_graph_snapshot(ontology=_basic_ontology())
    member_edges = [e for e in snap["edges"] if e["relation"] == "member_of"]
    pairs = {(e["source"], e["target"]) for e in member_edges}
    # Agent instance ids -> department ids (the AD-520 fix from this week)
    assert ("sci-1", "science") in pairs
    assert ("arch-1", "bridge") in pairs
    assert ("cap-1", "bridge") in pairs
    # Old format (agent_type -> post_id) is NOT emitted when the post resolves
    assert all(e["target"] not in {"first_officer", "captain", "science_officer"} for e in member_edges)


@pytest.mark.asyncio
async def test_reports_to_walks_past_unfilled_chief_science() -> None:
    """Science officer should report to the architect (dual-hatted first_officer)
    when chief_science is unfilled."""
    snap = await build_ontology_graph_snapshot(ontology=_basic_ontology())
    reports = {(e["source"], e["target"]) for e in snap["edges"] if e["relation"] == "reports_to"}
    assert ("sci-1", "arch-1") in reports
    # And the architect reports to the captain
    assert ("arch-1", "cap-1") in reports


@pytest.mark.asyncio
async def test_max_nodes_truncates() -> None:
    snap = await build_ontology_graph_snapshot(ontology=_basic_ontology(), max_nodes=2)
    assert len(snap["nodes"]) == 2


@pytest.mark.asyncio
async def test_knowledge_edges_skipped_when_disabled() -> None:
    class _BoomEdges:
        async def find_edges(self, **_kw):
            raise RuntimeError("must not be called")

    snap = await build_ontology_graph_snapshot(
        ontology=_basic_ontology(),
        knowledge_edges=_BoomEdges(),
        include_edges=False,
    )
    # Only assignment-derived edges
    assert all(e["relation"] in {"member_of", "reports_to"} for e in snap["edges"])


@pytest.mark.asyncio
async def test_minimal_ontology_without_get_posts_falls_back() -> None:
    """An ontology that doesn't expose get_posts emits legacy agent_type -> post_id edges."""

    class _Minimal(_StubOntology):
        def get_posts(self):  # type: ignore[override]
            raise NotImplementedError

    minimal = _Minimal(
        departments=[_Dept(id="science", name="Science")],
        posts=[],
        assignments=[_Assignment(agent_type="science_officer", post_id="science_officer")],
        manifest=[
            {"agent_type": "science_officer", "department": "science", "trust": 0.5},
        ],
    )
    snap = await build_ontology_graph_snapshot(ontology=minimal)
    member = [e for e in snap["edges"] if e["relation"] == "member_of"]
    assert any(
        e["source"] == "science_officer" and e["target"] == "science_officer"
        for e in member
    )


@pytest.mark.asyncio
async def test_generated_at_present() -> None:
    snap = await build_ontology_graph_snapshot(ontology=_basic_ontology())
    assert isinstance(snap["generated_at"], float)
    assert snap["generated_at"] > 0
