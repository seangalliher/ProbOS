"""AD-562: Tests for GET /api/records/graph."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.knowledge.backlinks import KnowledgeBrowserService
from probos.routers.records import get_records_graph


class _FakeStore:
    def __init__(self, entries: list[dict]) -> None:
        self._entries = entries

    async def list_entries(self, **_):
        return [{"path": e["path"], "frontmatter": e.get("frontmatter", {})} for e in self._entries]

    async def read_entry(self, path: str, *, reader_id: str = "captain", **_):
        for e in self._entries:
            if e["path"] == path:
                return {"frontmatter": e.get("frontmatter", {}), "content": e.get("content", "")}
        return None


class _FakeQuality:
    async def get_agent_snapshot(self, callsign: str):
        return SimpleNamespace(novel_content_rate=0.7, repetition_alerts=2, stale_rate=0.1)


def _runtime_with_service(service) -> MagicMock:
    rt = MagicMock(spec=[])
    rt.knowledge_browser = service
    return rt


def _make_service(entries, quality=None):
    return KnowledgeBrowserService(_FakeStore(entries), notebook_quality_engine=quality)


@pytest.mark.asyncio
async def test_graph_happy_path_with_quality() -> None:
    entries = [
        {"path": "notebooks/chapel/n1.md", "frontmatter": {"author": "chapel", "department": "medical", "topic_slug": "trust"}, "content": "ping @data"},
        {"path": "notebooks/data/n2.md", "frontmatter": {"author": "data", "department": "science"}, "content": ""},
    ]
    svc = _make_service(entries, quality=_FakeQuality())
    res = await get_records_graph(include_quality=True, runtime=_runtime_with_service(svc))
    assert isinstance(res, dict)
    assert res["node_count"] == 2
    chapel_node = next(n for n in res["nodes"] if n["author"] == "chapel")
    assert chapel_node["quality_overlay"] == {"novel_content_rate": 0.7, "repetition_alerts": 2, "stale_rate": 0.1}


@pytest.mark.asyncio
async def test_graph_convergence_hub_flag_and_edges() -> None:
    entries = [
        {"path": "notebooks/chapel/n1.md", "frontmatter": {"author": "chapel", "department": "medical"}, "content": ""},
        {"path": "convergence-reports/r1.md", "frontmatter": {"contributing_agents": ["chapel"], "department": "bridge"}, "content": ""},
    ]
    svc = _make_service(entries)
    res = await get_records_graph(runtime=_runtime_with_service(svc))
    hub = next(n for n in res["nodes"] if n["id"] == "convergence-reports/r1.md")
    assert hub["is_convergence_hub"] is True
    conv_edges = [e for e in res["edges"] if e["kind"] == "convergence"]
    assert len(conv_edges) == 1
    assert conv_edges[0]["source"] == "notebooks/chapel/n1.md"
    assert conv_edges[0]["target"] == "convergence-reports/r1.md"


@pytest.mark.asyncio
async def test_graph_max_nodes_cap_honored() -> None:
    entries = [{"path": f"n{i}.md", "frontmatter": {"author": f"a{i}"}, "content": ""} for i in range(20)]
    svc = _make_service(entries)
    res = await get_records_graph(max_nodes=5, runtime=_runtime_with_service(svc))
    assert res["node_count"] == 5


@pytest.mark.asyncio
async def test_graph_returns_503_when_service_none() -> None:
    rt = MagicMock(spec=[])
    res = await get_records_graph(runtime=rt)
    assert getattr(res, "status_code", 200) == 503


@pytest.mark.asyncio
async def test_graph_quality_overlay_absent_when_no_engine() -> None:
    entries = [
        {"path": "n1.md", "frontmatter": {"author": "chapel", "department": "medical"}, "content": ""},
    ]
    svc = _make_service(entries, quality=None)
    res = await get_records_graph(include_quality=True, runtime=_runtime_with_service(svc))
    assert res["nodes"][0]["quality_overlay"] is None
