"""AD-1041: tests for the ARD catalog projector (federation/ard/catalog_projector.py).

BF-287 real fixtures: a real ``SystemConfig``, a real ``McpServerStore``
(``db_path=""`` cache-only) for the MCP axis, and explicit ``_Fake*`` stub
classes (NOT MagicMock — no auto-attribute hazard) shaped to exactly what
``list_capability_catalog`` reads for the tools / skills / mesh axes.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1041_catalog_projector.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

from typing import Any

import pytest

from probos.config import SystemConfig
from probos.federation.ard import (
    MT_A2A_AGENT,
    MT_AI_SKILL,
    MT_MCP_SERVER,
    MT_PROBOS_TOOL,
    project_catalog,
)
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore


# --------------------------------------------------------------------------- #
# Explicit (non-Mock) stubs shaped to the real read sites
# --------------------------------------------------------------------------- #


class _FakeToolMeta:
    def __init__(self, d: dict[str, Any]) -> None:
        self._d = d

    def to_dict(self) -> dict[str, Any]:
        return dict(self._d)


class _FakeToolRegistry:
    def __init__(self, tools: list[_FakeToolMeta]) -> None:
        self._tools = tools

    def list_tools(self) -> list[_FakeToolMeta]:
        return list(self._tools)


class _FakeSkill:
    def __init__(self, name: str, description: str, department: str, min_rank: str, intents: list[str]) -> None:
        self.name = name
        self.description = description
        self.department = department
        self.min_rank = min_rank
        self.intents = list(intents)


class _FakeSkillCatalog:
    def __init__(self, entries: list[_FakeSkill]) -> None:
        self._entries = entries

    def list_entries(self) -> list[_FakeSkill]:
        return list(self._entries)


class _FakeDesc:
    def __init__(self, name: str, description: str, usage_hint: str, requires_consensus: bool, tier: str) -> None:
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


class _FakeCert:
    def __init__(self, vessel_name: str, ship_did: str) -> None:
        self.vessel_name = vessel_name
        self.ship_did = ship_did


class _FakeIdentityRegistry:
    def __init__(self, cert: _FakeCert | None) -> None:
        self._cert = cert

    def get_ship_certificate(self) -> _FakeCert | None:
        return self._cert


class _Runtime:
    """Real-attribute (non-Mock) runtime stub exposing exactly what the projector reads."""

    def __init__(self, **kw: Any) -> None:
        self.config = kw.get("config")
        self.tool_registry = kw.get("tool_registry")
        self.cognitive_skill_catalog = kw.get("cognitive_skill_catalog")
        self.registry = kw.get("registry")
        self.mcp_server_store = kw.get("mcp_server_store")
        self.identity_registry = kw.get("identity_registry")


async def _seeded_store() -> McpServerStore:
    store = McpServerStore(db_path="")
    await store.create(McpServerRecord(name="weather-mcp", type="http", url="https://mcp.example.com/weather"))
    await store.create(McpServerRecord(name="local-tool", type="stdio", command="run-cmd"))
    return store


def _full_runtime(store: McpServerStore) -> _Runtime:
    return _Runtime(
        config=SystemConfig(),
        tool_registry=_FakeToolRegistry([
            _FakeToolMeta({
                "tool_id": "read_file", "name": "Read File", "description": "reads a file",
                "tool_type": "file", "provider": "", "domain": "*", "department": None,
            }),
        ]),
        cognitive_skill_catalog=_FakeSkillCatalog([
            _FakeSkill("triage", "triage skill", "medical", "ensign", ["diagnose", "assess"]),
        ]),
        registry=_FakeRegistry([
            _FakeAgent("agent-1", [
                _FakeDesc("counselor_wellness_report", "wellness", "[MESH ...]", False, "domain"),
            ]),
        ]),
        mcp_server_store=store,
        identity_registry=_FakeIdentityRegistry(_FakeCert("USS Test", "did:probos:test")),
    )


def _entry(entries: list[dict[str, Any]], substr: str) -> dict[str, Any]:
    return next(e for e in entries if substr in e["identifier"])


# --------------------------------------------------------------------------- #
# Media type per axis + URN
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_each_axis_projects_correct_media_type() -> None:
    store = await _seeded_store()
    catalog = await project_catalog(_full_runtime(store))
    body = catalog.to_dict()
    entries = body["entries"]

    assert _entry(entries, ":tools:")["type"] == MT_PROBOS_TOOL
    assert _entry(entries, ":skills:")["type"] == MT_AI_SKILL
    assert _entry(entries, ":intents:")["type"] == MT_A2A_AGENT
    assert _entry(entries, "weather-mcp")["type"] == MT_MCP_SERVER
    assert _entry(entries, "local-tool")["type"] == MT_MCP_SERVER


@pytest.mark.asyncio
async def test_urns_use_publisher_domain_from_vessel_name() -> None:
    store = await _seeded_store()
    catalog = await project_catalog(_full_runtime(store))
    entries = catalog.to_dict()["entries"]

    assert entries  # non-empty
    for e in entries:
        assert e["identifier"].startswith("urn:air:uss-test:")


@pytest.mark.asyncio
async def test_skill_and_mesh_capabilities_and_consensus_flag() -> None:
    store = await _seeded_store()
    catalog = await project_catalog(_full_runtime(store))
    entries = catalog.to_dict()["entries"]

    skill = _entry(entries, ":skills:")
    assert skill["capabilities"] == ["diagnose", "assess"]
    mesh = _entry(entries, ":intents:")
    assert mesh["data"]["requiresConsensus"] is False
    assert mesh["data"]["tier"] == "domain"


# --------------------------------------------------------------------------- #
# Value-or-reference (DD-1)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_value_or_reference_holds_for_every_entry() -> None:
    store = await _seeded_store()
    catalog = await project_catalog(_full_runtime(store))
    entries = catalog.to_dict()["entries"]

    for e in entries:
        # Exactly one of url|data is serialized (the __post_init__ invariant).
        assert ("url" in e) ^ ("data" in e), e["identifier"]


@pytest.mark.asyncio
async def test_http_mcp_is_reference_stdio_is_inline_data() -> None:
    store = await _seeded_store()
    catalog = await project_catalog(_full_runtime(store))
    entries = catalog.to_dict()["entries"]

    http_entry = _entry(entries, "weather-mcp")
    assert http_entry["url"] == "https://mcp.example.com/weather"
    assert "data" not in http_entry

    stdio_entry = _entry(entries, "local-tool")
    assert "url" not in stdio_entry
    assert stdio_entry["data"]["serverType"] == "stdio"
    assert stdio_entry["data"]["axis"] == "mcp"


# --------------------------------------------------------------------------- #
# Honest-degrade (accessors absent)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_honest_degrade_host_only_when_accessors_absent() -> None:
    # No tool_registry / skill catalog / registry / mcp store / identity → host-only.
    runtime = _Runtime(config=SystemConfig())
    catalog = await project_catalog(runtime)
    body = catalog.to_dict()

    assert body["entries"] == []
    assert body["host"]["displayName"] == "ProbOS"
    assert body["specVersion"] == "1.0"


@pytest.mark.asyncio
async def test_host_reflects_vessel_name_when_present() -> None:
    store = await _seeded_store()
    catalog = await project_catalog(_full_runtime(store))
    assert catalog.to_dict()["host"]["displayName"] == "USS Test"
