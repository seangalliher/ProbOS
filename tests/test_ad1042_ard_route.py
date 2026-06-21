"""AD-1042: tests for the public ARD well-known route (routers/ard.py).

BF-287 real fixtures: a real ``SystemConfig`` (the default-OFF gate), a real
``McpServerStore`` (``db_path=""`` cache-only) seeded with worst-case
secret-bearing records to PROVE the projector reads only id/name/type/url
(DD-7), a real ``WorkflowCache``, and a real ``TestClient`` with
``app.state.runtime``. NO MagicMock at the config/store boundary.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1042_ard_route.py -q -n 0 -p no:cacheprovider
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
from probos.federation.ard import MT_AI_CATALOG, reset_catalog_cache
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore

_WELL_KNOWN = "/.well-known/ai-catalog.json"


@pytest.fixture(autouse=True)
def _reset_ard_cache() -> Iterator[None]:
    """Isolate the shared AD-1044 projection cache between tests (id(runtime) reuse)."""
    reset_catalog_cache()
    yield
    reset_catalog_cache()

# Worst-case secret-bearing records: EVERY credential field is populated with a
# distinctive token so the DD-7 test proves the projector never reads them.
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
_STDIO_SECRET = McpServerRecord(
    name="local-tool",
    type="stdio",
    command="run-cmd",
    args=["STDIOARGSECRET"],
    env={"K": "STDIOENVSECRET"},
    cwd="/STDIO_CWD",
)

_SECRET_VALUES = [
    "CRED_REF_TOKEN", "X-Hdr-Name", "SchemeToken", "ENVVARNAME", "OAUTHSECRETJSON",
    "HEADERSECRET", "ENVSECRET", "ARGSECRET", "CWDSECRET",
    "STDIOARGSECRET", "STDIOENVSECRET", "STDIO_CWD",
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


# --------------------------------------------------------------------------- #
# Gate (default-OFF)
# --------------------------------------------------------------------------- #


def test_gate_off_returns_404_feature_disabled() -> None:
    runtime = _Runtime(_config(enabled=False))
    resp = _client(runtime).get(_WELL_KNOWN)
    assert resp.status_code == 404
    assert resp.json()["detail"] == "feature_disabled"


def test_default_config_is_off() -> None:
    # The Pydantic default ships OFF — a bare SystemConfig 404s.
    runtime = _Runtime(SystemConfig())
    assert _client(runtime).get(_WELL_KNOWN).status_code == 404


# --------------------------------------------------------------------------- #
# Public when ON
# --------------------------------------------------------------------------- #


def test_on_returns_200_catalog_envelope() -> None:
    store = McpServerStore(db_path="")
    _seed(store, _HTTP_SECRET, _STDIO_SECRET)
    runtime = _Runtime(
        _config(enabled=True),
        mcp_server_store=store,
        workflow_cache=WorkflowCache(),
    )
    resp = _client(runtime).get(_WELL_KNOWN)

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith(MT_AI_CATALOG)
    body = resp.json()
    assert body["specVersion"] == "1.0"
    assert isinstance(body["entries"], list)
    assert len(body["entries"]) == 2  # the two seeded MCP servers


def test_every_entry_has_exactly_one_of_url_or_data() -> None:
    store = McpServerStore(db_path="")
    _seed(store, _HTTP_SECRET, _STDIO_SECRET)
    runtime = _Runtime(_config(enabled=True), mcp_server_store=store, workflow_cache=WorkflowCache())
    body = _client(runtime).get(_WELL_KNOWN).json()

    for entry in body["entries"]:
        assert ("url" in entry) ^ ("data" in entry), entry["identifier"]


# --------------------------------------------------------------------------- #
# DD-7 secrets-never-projected
# --------------------------------------------------------------------------- #


def test_dd7_response_contains_no_secret_values_or_field_names() -> None:
    store = McpServerStore(db_path="")
    _seed(store, _HTTP_SECRET, _STDIO_SECRET)
    runtime = _Runtime(_config(enabled=True), mcp_server_store=store, workflow_cache=WorkflowCache())
    text = _client(runtime).get(_WELL_KNOWN).text

    # The non-secret server NAME + url ARE projected (public discovery surface).
    assert "weather-mcp" in text
    assert "https://mcp.example.com/weather" in text
    # ...but NO credential value and NO secret-bearing field name leak.
    for token in _SECRET_VALUES:
        assert token not in text, f"secret value leaked: {token}"
    for field_name in _SECRET_FIELD_NAMES:
        assert field_name not in text, f"secret field name leaked: {field_name}"


# --------------------------------------------------------------------------- #
# Public route does not require episodic_memory (episodic_k=0)
# --------------------------------------------------------------------------- #


def test_route_works_with_episodic_memory_none() -> None:
    store = McpServerStore(db_path="")
    _seed(store, _HTTP_SECRET)
    runtime = _Runtime(
        _config(enabled=True),
        mcp_server_store=store,
        workflow_cache=WorkflowCache(),
        episodic_memory=None,  # the public path passes episodic_k=0 → never consulted
    )
    resp = _client(runtime).get(_WELL_KNOWN)

    assert resp.status_code == 200
    assert resp.json()["specVersion"] == "1.0"
