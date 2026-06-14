"""AD-1001: Ship's Locker — global capabilities catalog (GET /api/tools/catalog).

The ship-wide read-only counterpart to the per-agent Service hub (AD-1000):
aggregates tools + skills + mesh intents + MCP servers, with ``held_by`` (which
crew hold each per-agent capability by explicit grant).

BF-287: real ToolRegistry + real ToolPermissionStore / SkillGrantStore (DB-less
sync cache) + real CognitiveSkillEntry + real IntentDescriptor; a hand-written
registry stub whose ``.all()`` returns real agent-like objects (no MagicMock at
the registry boundary).
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.cognitive.skill_catalog import CognitiveSkillEntry
from probos.cognitive.skill_grants import SkillGrantStore
from probos.config import MCPConfig, MCPServerConfig
from probos.routers import tools as tools_router
from probos.routers.deps import get_runtime
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import Tool, ToolPermission, ToolResult, ToolType
from probos.tools.registry import ToolRegistry
from probos.types import IntentDescriptor


class _StubTool:
    def __init__(self, tid: str, tt: ToolType = ToolType.DETERMINISTIC_FUNCTION, provider: str = "") -> None:
        self._tid, self._tt, self._provider = tid, tt, provider

    @property
    def tool_id(self) -> str: return self._tid
    @property
    def name(self) -> str: return self._tid
    @property
    def tool_type(self) -> ToolType: return self._tt
    @property
    def description(self) -> str: return f"{self._tid} tool"
    @property
    def input_schema(self) -> dict[str, Any]: return {"type": "object"}
    @property
    def output_schema(self) -> dict[str, Any]: return {"type": "string"}
    async def invoke(self, params: dict[str, Any], context: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(output="ok")


class _Catalog:
    def __init__(self, entries: list[CognitiveSkillEntry]) -> None:
        self._entries = entries
    def list_entries(self, *a, **k) -> list[CognitiveSkillEntry]:
        return list(self._entries)


class _Registry:
    def __init__(self, agents: list[Any]) -> None:
        self._agents = agents
    def all(self) -> list[Any]:
        return list(self._agents)


def _build():
    """Construct a runtime with real stores + grants. Returns (runtime, cleanup)."""
    reg = ToolRegistry()
    reg.register(_StubTool("file_reader"))
    reg.register(_StubTool("mcp_db", ToolType.MCP_SERVER))
    reg.register(_StubTool("designed_x"), provider="extension")

    async def _setup():
        perms = ToolPermissionStore(db_path="")
        await perms.start()
        skills = SkillGrantStore(db_path="")
        await skills.start()
        await perms.issue_grant("ezri", "file_reader", ToolPermission.READ, reason="x", issued_by="captain")
        await skills.issue_grant("ezri", "diagnose", reason="x")
        return perms, skills

    perms, skills = asyncio.run(_setup())

    catalog = _Catalog([
        CognitiveSkillEntry(name="diagnose", description="Diagnose", skill_dir=Path("diagnose"), department="medical", min_rank="ensign", intents=["diagnose"]),
        CognitiveSkillEntry(name="summarize", description="Summarize", skill_dir=Path("summarize"), department="*"),
    ])
    registry = _Registry([
        SimpleNamespace(id="ezri", intent_descriptors=[
            IntentDescriptor(name="run_python", description="Run a script", requires_consensus=True, tier="core"),
        ]),
        SimpleNamespace(id="yeo", intent_descriptors=[]),
    ])
    config = SimpleNamespace(mcp=MCPConfig(enabled=True, servers=[MCPServerConfig(url="http://localhost:9000")]))
    runtime = SimpleNamespace(
        registry=registry, tool_registry=reg, tool_permission_store=perms,
        skill_grant_store=skills, cognitive_skill_catalog=catalog, config=config,
    )

    async def _teardown():
        await perms.stop()
        await skills.stop()

    return runtime, _teardown


def _client(runtime) -> TestClient:
    app = FastAPI()
    app.include_router(tools_router.router)
    app.dependency_overrides[get_runtime] = lambda: runtime
    return TestClient(app)


def test_catalog_aggregates_all_four_axes():
    runtime, teardown = _build()
    try:
        body = _client(runtime).get("/api/tools/catalog").json()
        assert body["counts"]["tools"] == 3
        assert body["counts"]["skills"] == 2
        assert body["counts"]["mesh_intents"] == 1
        assert body["counts"]["mcp_servers"] == 1
        tool_ids = {t["id"] for t in body["tools"]}
        assert tool_ids == {"file_reader", "mcp_db", "designed_x"}
        skill_ids = {s["id"] for s in body["skills"]}
        assert skill_ids == {"diagnose", "summarize"}
        assert body["mesh_intents"][0]["name"] == "run_python"
        assert body["mcp_servers"][0]["url"] == "http://localhost:9000"
    finally:
        asyncio.run(teardown())


def test_catalog_tool_origin_taxonomy():
    runtime, teardown = _build()
    try:
        body = _client(runtime).get("/api/tools/catalog").json()
        by_id = {t["id"]: t for t in body["tools"]}
        assert by_id["file_reader"]["origin"] == "built_in"
        assert by_id["mcp_db"]["origin"] == "mcp"
        assert by_id["designed_x"]["origin"] == "extension"
    finally:
        asyncio.run(teardown())


def test_catalog_held_by_reflects_explicit_grants():
    runtime, teardown = _build()
    try:
        body = _client(runtime).get("/api/tools/catalog").json()
        fr = next(t for t in body["tools"] if t["id"] == "file_reader")
        assert fr["held_by"] == ["ezri"]
        mcp_db = next(t for t in body["tools"] if t["id"] == "mcp_db")
        assert mcp_db["held_by"] == []   # no explicit grant
        diagnose = next(s for s in body["skills"] if s["id"] == "diagnose")
        assert diagnose["held_by"] == ["ezri"]
    finally:
        asyncio.run(teardown())


def test_catalog_mesh_intents_have_no_held_by():
    runtime, teardown = _build()
    try:
        body = _client(runtime).get("/api/tools/catalog").json()
        # Mesh intents are ship-served — reachable, no per-agent held_by field.
        mi = body["mesh_intents"][0]
        assert mi["reachable"] is True
        assert "held_by" not in mi
    finally:
        asyncio.run(teardown())


def test_catalog_honest_degrade_empty_runtime():
    body = _client(SimpleNamespace()).get("/api/tools/catalog").json()
    assert body["counts"] == {"tools": 0, "skills": 0, "mesh_intents": 0, "mcp_servers": 0}
    assert body["tools"] == [] and body["skills"] == [] and body["mesh_intents"] == []
