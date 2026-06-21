"""AD-1051: tests for ARD catalog publication (default-OFF + secret-free).

DD-3 default-OFF + secret-free + BF-287 real fixtures: an empty ``registry_url`` is a
no-op with NO HTTP call (an exploding ``MockTransport`` proves it is never touched).
The success / http-error / honest-degrade outcomes are exercised with a real
``httpx.AsyncClient`` over an ``httpx.MockTransport`` against a real catalog
projection from a real ``McpServerStore(db_path="")``. The secrets-never test seeds
a worst-case secret-bearing ``McpServerRecord`` and asserts the POSTED JSON carries
none of the credential field-name / value sentinels (DD-7).

asyncio_mode="auto": async tests carry NO ``@pytest.mark.asyncio`` marker; the
seeded secrets test ``await``s ``store.create`` directly inside the test's running
loop (no ``asyncio.run`` / private loop, which would corrupt the auto-mode loop).

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1051_ard_publication.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import httpx
import pytest

from probos.cognitive.workflow_cache import WorkflowCache
from probos.config import FederationArdConfig, FederationConfig, SystemConfig
from probos.federation.ard import publish_catalog, reset_catalog_cache
from probos.integrations.mcp_bridge.store import McpServerRecord, McpServerStore

_REGISTRY_URL = "https://registry.example.com/publish"

# Worst-case secret-bearing record (mirrors test_ad1042/1044) — proves the SAME
# projected entries flow through publish with no credential leak (DD-7).
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


@pytest.fixture(autouse=True)
def _reset_ard_cache() -> Iterator[None]:
    """Isolate the shared projection cache between tests (id(runtime) reuse)."""
    reset_catalog_cache()
    yield
    reset_catalog_cache()


class _PubRuntime:
    """Real-attribute runtime stub exposing exactly what publish + projector read."""

    def __init__(self, config: SystemConfig, **kw: Any) -> None:
        self.config = config
        self.mcp_server_store = kw.get("mcp_server_store")
        self.workflow_cache = kw.get("workflow_cache")
        self.registry = kw.get("registry")
        self.identity_registry = kw.get("identity_registry")
        self.episodic_memory = kw.get("episodic_memory")


def _config(*, registry_url: str = _REGISTRY_URL) -> SystemConfig:
    return SystemConfig(
        federation=FederationConfig(
            ard=FederationArdConfig(enabled=True, registry_url=registry_url)
        )
    )


def _runtime(*, registry_url: str = _REGISTRY_URL) -> _PubRuntime:
    return _PubRuntime(
        _config(registry_url=registry_url),
        mcp_server_store=McpServerStore(db_path=""),
        workflow_cache=WorkflowCache(),
    )


# --------------------------------------------------------------------------- #
# publish_catalog
# --------------------------------------------------------------------------- #


async def test_publish_empty_registry_url_no_http() -> None:
    def _explode(request: httpx.Request) -> httpx.Response:
        raise AssertionError("HTTP must not be called with an empty registry_url")

    client = httpx.AsyncClient(transport=httpx.MockTransport(_explode))
    try:
        rt = _runtime(registry_url="")
        result = await publish_catalog(rt, http=client)
    finally:
        await client.aclose()
    assert result.published is False
    assert result.reason == "no_registry_url"
    assert result.status_code is None


async def test_publish_success_200() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        result = await publish_catalog(_runtime(), http=client)
    finally:
        await client.aclose()
    assert result.published is True
    assert result.status_code == 200
    assert result.reason == ""


async def test_publish_http_error_500() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        result = await publish_catalog(_runtime(), http=client)
    finally:
        await client.aclose()
    assert result.published is False
    assert result.status_code == 500
    assert result.reason == "http_error"


async def test_publish_honest_degrade_on_exception() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        raise RuntimeError("connection exploded")

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        result = await publish_catalog(_runtime(), http=client)
    finally:
        await client.aclose()
    assert result.published is False
    # An exception-degrade carries no status code and a non-empty reason.
    assert result.status_code is None
    assert result.reason
    assert result.reason not in ("http_error", "no_registry_url")


async def test_publish_body_carries_no_secrets() -> None:
    posted: dict[str, str] = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        posted["body"] = request.content.decode()
        return httpx.Response(200, json={"ok": True})

    store = McpServerStore(db_path="")
    await store.create(_HTTP_SECRET)
    rt = _PubRuntime(_config(), mcp_server_store=store, workflow_cache=WorkflowCache())
    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    try:
        result = await publish_catalog(rt, http=client)
    finally:
        await client.aclose()
    assert result.published is True
    body = posted["body"]
    for sentinel in _SECRET_FIELD_NAMES:
        assert sentinel not in body, f"secret field name {sentinel!r} leaked into published body"
    for value in _SECRET_VALUES:
        assert value not in body, f"secret value {value!r} leaked into published body"
