"""AD-1045: tests for ``POST /ard/explore`` (facets) + ``GET /ard/agents``.

BF-287 real fixtures: a real ``SystemConfig`` gate, a real ``McpServerStore``
(``db_path=""`` cache-only), a real ``WorkflowCache``, a real ``TestClient`` with
``app.state.runtime``, and explicit ``_Fake*`` stubs (NOT MagicMock) for the
mesh-intent axis so the catalog contains real ``MT_A2A_AGENT`` entries for the
``/ard/agents`` view. The pure ``facet_entries`` counter is unit-tested directly.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1045_ard_explore_agents.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.workflow_cache import WorkflowCache
from probos.config import FederationArdConfig, FederationConfig, SystemConfig
from probos.federation.ard import (
    MT_A2A_AGENT,
    MT_AI_REGISTRY,
    MT_AI_SKILL,
    MT_MCP_SERVER,
    MT_PROBOS_TOOL,
    CatalogEntry,
    facet_entries,
    reset_catalog_cache,
)
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore

_EXPLORE = "/ard/explore"
_AGENTS = "/ard/agents"


@pytest.fixture(autouse=True)
def _reset_ard_cache() -> Iterator[None]:
    """Isolate the shared AD-1044 projection cache between tests (id(runtime) reuse)."""
    reset_catalog_cache()
    yield
    reset_catalog_cache()


# --------------------------------------------------------------------------- #
# Explicit (non-Mock) mesh-axis stubs (the only MT_A2A_AGENT producer)
# --------------------------------------------------------------------------- #


class _FakeDesc:
    def __init__(self, name: str, description: str, usage_hint: str,
                 requires_consensus: bool, tier: str) -> None:
        self.name = name
        self.description = description
        self.usage_hint = usage_hint
        self.requires_consensus = requires_consensus
        self.tier = tier


class _FakeAgent:
    def __init__(self, agent_id: str, descriptors: list[_FakeDesc]) -> None:
        self.id = agent_id
        self.intent_descriptors = list(descriptors)


class _FakeRegistry:
    def __init__(self, agents: list[_FakeAgent]) -> None:
        self._agents = agents

    def all(self) -> list[_FakeAgent]:
        return list(self._agents)


class _Runtime:
    """Real-attribute runtime stub exposing exactly what the route + projector read."""

    def __init__(self, config: SystemConfig, **kw: Any) -> None:
        self.config = config
        self.mcp_server_store = kw.get("mcp_server_store")
        self.workflow_cache = kw.get("workflow_cache")
        self.registry = kw.get("registry")
        self.identity_registry = kw.get("identity_registry")
        self.episodic_memory = kw.get("episodic_memory")


def _config(*, enabled: bool) -> SystemConfig:
    return SystemConfig(federation=FederationConfig(ard=FederationArdConfig(enabled=enabled)))


def _seed(store: McpServerStore, *records: McpServerRecord) -> None:
    async def _run() -> None:
        for rec in records:
            await store.create(rec)

    asyncio.run(_run())


def _client(runtime: _Runtime) -> TestClient:
    from probos.routers.ard import router

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app)


def _mixed_runtime() -> _Runtime:
    """One mesh-intent (MT_A2A_AGENT) + two stdio MCP servers (MT_MCP_SERVER)."""
    store = McpServerStore(db_path="")
    _seed(
        store,
        McpServerRecord(name="srv-a", type="stdio", command="c"),
        McpServerRecord(name="srv-b", type="stdio", command="c"),
    )
    registry = _FakeRegistry([
        _FakeAgent("agent-1", [
            _FakeDesc("counselor_wellness_report", "wellness", "", False, "domain"),
        ]),
    ])
    return _Runtime(
        _config(enabled=True),
        mcp_server_store=store,
        workflow_cache=WorkflowCache(),
        registry=registry,
    )


# --------------------------------------------------------------------------- #
# Pure facet_entries
# --------------------------------------------------------------------------- #


def test_facet_entries_counts_types_tags_axes() -> None:
    tool = CatalogEntry(
        identifier="urn:a:tools:x", display_name="X", type=MT_PROBOS_TOOL,
        data={"axis": "tool"}, tags=["core"],
    )
    skill = CatalogEntry(
        identifier="urn:a:skills:y", display_name="Y", type=MT_AI_SKILL,
        data={"axis": "skill"}, tags=["medical"],
    )
    # A reference entry (url, no data) contributes a type + no axis.
    ref = CatalogEntry(
        identifier="urn:a:mcp:z", display_name="Z", type=MT_MCP_SERVER,
        url="https://example.com/z",
    )
    facets = facet_entries([tool, skill, ref])

    assert facets["types"] == {MT_PROBOS_TOOL: 1, MT_AI_SKILL: 1, MT_MCP_SERVER: 1}
    assert facets["tags"] == {"core": 1, "medical": 1}
    assert facets["axes"] == {"tool": 1, "skill": 1}  # ref (url-only) has no axis


def test_facet_entries_empty_is_empty_maps() -> None:
    assert facet_entries([]) == {"types": {}, "tags": {}, "axes": {}}


# --------------------------------------------------------------------------- #
# /ard/explore
# --------------------------------------------------------------------------- #


def test_explore_gate_off_returns_404() -> None:
    runtime = _Runtime(_config(enabled=False))
    resp = _client(runtime).post(_EXPLORE, json={})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "feature_disabled"


def test_explore_returns_facets_and_results() -> None:
    resp = _client(_mixed_runtime()).post(_EXPLORE, json={})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(MT_AI_REGISTRY)
    body = resp.json()
    assert body["specVersion"] == "1.0"
    assert body["conformance"] == "registry"

    facets = body["facets"]
    assert facets["types"].get(MT_A2A_AGENT) == 1
    assert facets["types"].get(MT_MCP_SERVER) == 2
    assert facets["tags"].get("domain") == 1  # the mesh entry's tier tag
    assert facets["axes"].get("mesh_intent") == 1
    assert facets["axes"].get("mcp") == 2

    assert body["total"] == 3
    assert len(body["results"]) == 3


def test_explore_paginates_results() -> None:
    body = _client(_mixed_runtime()).post(_EXPLORE, json={"pageSize": 1}).json()
    assert body["total"] == 3
    assert len(body["results"]) == 1
    assert body["nextPageToken"] == "1"


# --------------------------------------------------------------------------- #
# GET /ard/agents
# --------------------------------------------------------------------------- #


def test_agents_gate_off_returns_404() -> None:
    runtime = _Runtime(_config(enabled=False))
    resp = _client(runtime).get(_AGENTS)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "feature_disabled"


def test_agents_returns_only_a2a_agent_entries() -> None:
    resp = _client(_mixed_runtime()).get(_AGENTS)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(MT_AI_REGISTRY)
    body = resp.json()
    # Only the single mesh-intent entry is an agent card; the 2 MCP servers are excluded.
    assert body["total"] == 1
    assert len(body["results"]) == 1
    assert all(r["type"] == MT_A2A_AGENT for r in body["results"])
    assert "counselor_wellness_report" in body["results"][0]["identifier"]


def test_agents_text_query_ranks_within_agent_axis() -> None:
    body = _client(_mixed_runtime()).get(_AGENTS, params={"text": "counselor"}).json()
    assert body["total"] == 1
    assert "counselor_wellness_report" in body["results"][0]["identifier"]
