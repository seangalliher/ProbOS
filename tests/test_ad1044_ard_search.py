"""AD-1044: tests for ``POST /ard/search`` + the DD-4 projection cache.

BF-287 real fixtures: a real ``SystemConfig`` gate, a real ``McpServerStore``
(``db_path=""`` cache-only), a real ``WorkflowCache``, and a real ``TestClient``
with ``app.state.runtime`` (mirrors tests/test_ad1042_ard_route.py). NO
MagicMock at the config/store boundary. The pure ``search_entries`` ranking +
the ``_clamp_page_size`` bound are unit-tested directly on hand-built
``CatalogEntry`` lists for full control.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1044_ard_search.py -q -n 0 -p no:cacheprovider
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
    get_cached_catalog,
    reset_catalog_cache,
    search_entries,
)
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore
from probos.routers.ard import _clamp_page_size

_SEARCH = "/ard/search"


@pytest.fixture(autouse=True)
def _reset_ard_cache() -> Iterator[None]:
    """Isolate the shared AD-1044 projection cache between tests (id(runtime) reuse)."""
    reset_catalog_cache()
    yield
    reset_catalog_cache()


# Worst-case secret-bearing record (mirrors test_ad1042) — proves the SAME
# projected entries flow through /ard/search with no credential leak (DD-6/DD-7).
_HTTP_SECRET = McpServerRecord(
    name="weather-mcp",
    type="http",
    url="https://mcp.example.com/weather",
    auth_kind="oauth",
    credential_ref="vault://CRED_REF_TOKEN",
    auth_header_name="X-Hdr-Name",
    auth_scheme="SchemeToken",
    auth_env_var="ENVVARNAME",
    oauth_json='{"client_secret":"OAUTHSECRETJSON"}',
    headers={"X-H": "HEADERSECRET"},
    env={"E": "ENVSECRET"},
    command="cmd",
    args=["ARGSECRET"],
    cwd="/CWDSECRET",
)
_SECRET_VALUES = [
    "CRED_REF_TOKEN", "X-Hdr-Name", "SchemeToken", "ENVVARNAME", "OAUTHSECRETJSON",
    "HEADERSECRET", "ENVSECRET", "ARGSECRET", "CWDSECRET",
]
_SECRET_FIELD_NAMES = [
    "auth_kind", "credential_ref", "auth_header_name", "auth_scheme",
    "auth_env_var", "oauth_json", "headers", "command", "args", "cwd", "env",
]


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
    # Loop-safe seeding: a private event loop that never touches the global
    # asyncio policy. asyncio.run() resets the policy loop, which corrupts
    # pytest-asyncio's (asyncio_mode=auto) loop for adjacent async tests under
    # random ordering -> "asyncio.run() cannot be called from a running loop".
    async def _run() -> None:
        for rec in records:
            await store.create(rec)

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_run())
    finally:
        loop.close()


def _client(runtime: _Runtime) -> TestClient:
    from probos.routers.ard import router

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app)


def _enabled_runtime(*records: McpServerRecord) -> _Runtime:
    store = McpServerStore(db_path="")
    if records:
        _seed(store, *records)
    return _Runtime(_config(enabled=True), mcp_server_store=store, workflow_cache=WorkflowCache())


# --------------------------------------------------------------------------- #
# Pure search_entries ranking + filter (hand-built CatalogEntry lists)
# --------------------------------------------------------------------------- #


def _tool(identifier: str, name: str, *, desc: str = "", tags: list[str] | None = None,
          caps: list[str] | None = None, type: str = MT_PROBOS_TOOL) -> CatalogEntry:
    return CatalogEntry(
        identifier=identifier, display_name=name, type=type, data={"axis": "tool"},
        description=desc, tags=tags or [], capabilities=caps or [],
    )


def test_search_entries_ranks_name_above_description() -> None:
    name_hit = _tool("urn:a:tools:weather", "Weather Service", caps=["get_weather"])
    desc_hit = _tool("urn:a:tools:logger", "Logger", desc="weather logs mention weather")
    ranked = search_entries([desc_hit, name_hit], "weather")
    assert [e.identifier for e in ranked] == ["urn:a:tools:weather", "urn:a:tools:logger"]


def test_search_entries_empty_text_returns_all_unfiltered() -> None:
    e1 = _tool("urn:a:tools:one", "One")
    e2 = _tool("urn:a:tools:two", "Two")
    assert search_entries([e1, e2], "") == [e1, e2]


def test_search_entries_filter_type_exact_match() -> None:
    tool = _tool("urn:a:tools:x", "X")
    skill = _tool("urn:a:skills:y", "Y", type=MT_AI_SKILL)
    assert search_entries([tool, skill], "", type=MT_AI_SKILL) == [skill]


def test_search_entries_filter_tags_is_and() -> None:
    both = _tool("urn:a:tools:both", "Both", tags=["a", "b"])
    one = _tool("urn:a:tools:one", "One", tags=["a"])
    assert search_entries([both, one], "", tags=["a", "b"]) == [both]
    assert set(e.identifier for e in search_entries([both, one], "", tags=["a"])) == {
        "urn:a:tools:both", "urn:a:tools:one",
    }


def test_search_entries_drops_zero_score() -> None:
    e1 = _tool("urn:a:tools:one", "One", caps=["alpha"])
    assert search_entries([e1], "zzznomatch") == []


def test_search_entries_tie_sorts_by_identifier() -> None:
    apple = _tool("urn:a:tools:apple", "match thing")
    banana = _tool("urn:a:tools:banana", "match thing")
    ranked = search_entries([banana, apple], "match")
    assert [e.identifier for e in ranked] == ["urn:a:tools:apple", "urn:a:tools:banana"]


# --------------------------------------------------------------------------- #
# _clamp_page_size unit (honest-degrade, never 422)
# --------------------------------------------------------------------------- #


def test_clamp_page_size_bounds() -> None:
    assert _clamp_page_size(1000) == 50
    assert _clamp_page_size(51) == 50
    assert _clamp_page_size(50) == 50
    assert _clamp_page_size(20) == 20
    assert _clamp_page_size(1) == 1
    assert _clamp_page_size(0) == 1
    assert _clamp_page_size(-5) == 1


# --------------------------------------------------------------------------- #
# DD-4 projection cache
# --------------------------------------------------------------------------- #


async def test_get_cached_catalog_returns_same_object_within_ttl() -> None:
    runtime = _enabled_runtime()  # unseeded: identity, not contents, is under test
    first = await get_cached_catalog(runtime)
    second = await get_cached_catalog(runtime)
    assert first is second  # served from the slot, no re-projection


async def test_reset_catalog_cache_forces_reprojection() -> None:
    runtime = _enabled_runtime()
    first = await get_cached_catalog(runtime)
    reset_catalog_cache()
    third = await get_cached_catalog(runtime)
    assert third is not first


async def test_ttl_zero_never_caches() -> None:
    runtime = _enabled_runtime()
    a = await get_cached_catalog(runtime, ttl=0)
    b = await get_cached_catalog(runtime, ttl=0)
    assert a is not b  # ttl<=0 re-projects and does NOT store


# --------------------------------------------------------------------------- #
# Endpoint: gate (default-OFF)
# --------------------------------------------------------------------------- #


def test_search_gate_off_returns_404_feature_disabled() -> None:
    runtime = _Runtime(_config(enabled=False))
    resp = _client(runtime).post(_SEARCH, json={"query": {"text": "weather"}})
    assert resp.status_code == 404
    assert resp.json()["detail"] == "feature_disabled"


# --------------------------------------------------------------------------- #
# Endpoint: ranking + envelope
# --------------------------------------------------------------------------- #


def test_search_returns_ranked_registry_envelope() -> None:
    runtime = _enabled_runtime(
        _HTTP_SECRET,  # weather-mcp (http)
        McpServerRecord(name="local-tool", type="stdio", command="run-cmd"),
    )
    resp = _client(runtime).post(_SEARCH, json={"query": {"text": "weather"}})

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(MT_AI_REGISTRY)
    body = resp.json()
    assert body["specVersion"] == "1.0"
    assert body["conformance"] == "registry"
    # "weather" matches only weather-mcp; local-tool scores 0 and is dropped.
    assert body["total"] == 1
    assert len(body["results"]) == 1
    assert "weather-mcp" in body["results"][0]["identifier"]


def test_search_empty_text_returns_all_entries() -> None:
    runtime = _enabled_runtime(
        McpServerRecord(name="a-srv", type="stdio", command="c"),
        McpServerRecord(name="b-srv", type="stdio", command="c"),
    )
    body = _client(runtime).post(_SEARCH, json={"query": {"text": ""}}).json()
    assert body["total"] == 2
    assert len(body["results"]) == 2


def test_search_filter_type_only_returns_matching_type() -> None:
    runtime = _enabled_runtime(
        _HTTP_SECRET,
        McpServerRecord(name="local-tool", type="stdio", command="run-cmd"),
    )
    # All seeded entries are MCP servers → filtering to MCP returns both...
    mcp = _client(runtime).post(
        _SEARCH, json={"query": {"text": "", "filter": {"type": MT_MCP_SERVER}}}
    ).json()
    assert mcp["total"] == 2
    assert all(r["type"] == MT_MCP_SERVER for r in mcp["results"])
    # ...and an exact filter for the agent media type excludes them all.
    agents = _client(runtime).post(
        _SEARCH, json={"query": {"text": "", "filter": {"type": MT_A2A_AGENT}}}
    ).json()
    assert agents["total"] == 0
    assert agents["results"] == []


# --------------------------------------------------------------------------- #
# Endpoint: pagination + clamp
# --------------------------------------------------------------------------- #


def test_search_page_size_clamped_to_50() -> None:
    records = [McpServerRecord(name=f"srv-{i:02d}", type="stdio", command="c") for i in range(60)]
    runtime = _enabled_runtime(*records)
    body = _client(runtime).post(_SEARCH, json={"query": {"text": ""}, "pageSize": 1000}).json()
    assert body["total"] == 60
    assert len(body["results"]) == 50  # clamped, NOT 60 and NOT a 422
    assert body["nextPageToken"] == "50"


def test_search_pagination_walks_distinct_pages() -> None:
    records = [McpServerRecord(name=f"srv-{i}", type="stdio", command="c") for i in range(5)]
    runtime = _enabled_runtime(*records)
    client = _client(runtime)

    page1 = client.post(_SEARCH, json={"query": {"text": ""}, "pageSize": 2}).json()
    assert len(page1["results"]) == 2
    assert page1["nextPageToken"] == "2"

    page2 = client.post(
        _SEARCH, json={"query": {"text": ""}, "pageSize": 2, "pageToken": "2"}
    ).json()
    assert len(page2["results"]) == 2
    assert page2["nextPageToken"] == "4"

    page3 = client.post(
        _SEARCH, json={"query": {"text": ""}, "pageSize": 2, "pageToken": "4"}
    ).json()
    assert len(page3["results"]) == 1
    assert page3["nextPageToken"] == ""  # exhausted

    ids = {r["identifier"] for r in page1["results"] + page2["results"] + page3["results"]}
    assert len(ids) == 5  # the three pages cover distinct entries


# --------------------------------------------------------------------------- #
# DD-6/DD-7 secrets-never (the same projected entries flow through search)
# --------------------------------------------------------------------------- #


def test_search_response_leaks_no_secret_values_or_field_names() -> None:
    runtime = _enabled_runtime(_HTTP_SECRET)
    text = _client(runtime).post(_SEARCH, json={"query": {"text": ""}}).text

    # The non-secret name + url ARE projected (public discovery surface)...
    assert "weather-mcp" in text
    assert "https://mcp.example.com/weather" in text
    # ...but NO credential value and NO secret-bearing field name leak.
    for token in _SECRET_VALUES:
        assert token not in text, f"secret value leaked: {token}"
    for field_name in _SECRET_FIELD_NAMES:
        assert field_name not in text, f"secret field name leaked: {field_name}"
