"""AD-1048: tests for per-agent ARD access resolution + operator endpoints.

DD-3 deny-default: the pure ``resolve_ard_access`` ladder is unit-tested with
hand-built ``ToolAccessGrant`` records (no store). ``ard_access_for_agent`` and
the operator endpoints use a REAL ``ToolPermissionStore(db_path="")`` (cache-only,
BF-287) and a real ``TestClient`` — no MagicMock.

asyncio_mode="auto": async tests carry NO marker; no ``asyncio.run`` is used.

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1048_ard_access.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from probos.config import FederationArdConfig, FederationConfig, SystemConfig
from probos.federation.ard import (
    ard_access_for_agent,
    ard_resource_tool_id,
    ard_tool_tool_id,
    reset_catalog_cache,
    resolve_ard_access,
)
from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolAccessGrant, ToolPermission


@pytest.fixture(autouse=True)
def _reset_ard_cache() -> Iterator[None]:
    reset_catalog_cache()
    yield
    reset_catalog_cache()


def _grant(tool_id: str, *, is_restriction: bool = False, agent_id: str = "a") -> ToolAccessGrant:
    return ToolAccessGrant(
        id="g",
        agent_id=agent_id,
        tool_id=tool_id,
        permission=ToolPermission.NONE if is_restriction else ToolPermission.READ,
        is_restriction=is_restriction,
        issued_by="test",
        issued_at=0.0,
    )


# --------------------------------------------------------------------------- #
# Composite id helpers
# --------------------------------------------------------------------------- #


def test_composite_id_helpers() -> None:
    assert ard_resource_tool_id("cat", "res") == "ard:cat:res"
    assert ard_tool_tool_id("cat", "res", "tool") == "ard:cat:res:tool"


# --------------------------------------------------------------------------- #
# Pure resolve_ard_access — deny-by-default ladder
# --------------------------------------------------------------------------- #


def test_no_grants_default_disabled() -> None:
    assert resolve_ard_access([], "cat", "res", "tool") == (False, "default")


def test_tool_grant_enables() -> None:
    grants = [_grant(ard_tool_tool_id("cat", "res", "tool"))]
    assert resolve_ard_access(grants, "cat", "res", "tool") == (True, "tool")


def test_tool_restriction_beats_tool_grant() -> None:
    grants = [
        _grant(ard_tool_tool_id("cat", "res", "tool")),
        _grant(ard_tool_tool_id("cat", "res", "tool"), is_restriction=True),
    ]
    assert resolve_ard_access(grants, "cat", "res", "tool") == (False, "tool")


def test_resource_scope_grant_applies_to_any_tool() -> None:
    grants = [_grant(ard_resource_tool_id("cat", "res"))]
    assert resolve_ard_access(grants, "cat", "res", "anytool") == (True, "resource")


def test_tool_scope_outranks_resource_scope() -> None:
    # Resource grant enables broadly, but a tool-scope restriction is more specific.
    grants = [
        _grant(ard_resource_tool_id("cat", "res")),
        _grant(ard_tool_tool_id("cat", "res", "tool"), is_restriction=True),
    ]
    assert resolve_ard_access(grants, "cat", "res", "tool") == (False, "tool")


def test_department_tool_grant_enables() -> None:
    dept = [_grant(ard_tool_tool_id("cat", "res", "tool"), agent_id="dept")]
    assert resolve_ard_access([], "cat", "res", "tool", department_grants=dept) == (True, "department")


def test_agent_tool_grant_over_dept_tool_restriction() -> None:
    agent = [_grant(ard_tool_tool_id("cat", "res", "tool"))]
    dept = [_grant(ard_tool_tool_id("cat", "res", "tool"), is_restriction=True, agent_id="dept")]
    assert resolve_ard_access(agent, "cat", "res", "tool", department_grants=dept) == (True, "tool")


def test_empty_tool_degrades_to_resource_scope() -> None:
    grants = [_grant(ard_resource_tool_id("cat", "res"))]
    assert resolve_ard_access(grants, "cat", "res", "") == (True, "resource")


# --------------------------------------------------------------------------- #
# Store-backed ard_access_for_agent (real ToolPermissionStore, cache-only)
# --------------------------------------------------------------------------- #


def test_ard_access_for_agent_deny_default_empty_store() -> None:
    store = ToolPermissionStore(db_path="")
    assert ard_access_for_agent(store, "agent-1", "cat", "res", "tool") == (False, "default")


async def test_ard_access_for_agent_reads_store_grant() -> None:
    store = ToolPermissionStore(db_path="")
    await store.issue_grant("agent-1", ard_resource_tool_id("cat", "res"), ToolPermission.READ)
    assert ard_access_for_agent(store, "agent-1", "cat", "res", "anytool") == (True, "resource")
    # A different agent is unaffected (deny-default).
    assert ard_access_for_agent(store, "agent-2", "cat", "res", "anytool") == (False, "default")


# --------------------------------------------------------------------------- #
# Operator endpoints (TestClient over a real router + runtime stub)
# --------------------------------------------------------------------------- #


class _Runtime:
    """Real-attribute runtime stub exposing exactly what the endpoints read."""

    def __init__(self, config: SystemConfig, *, tool_permission_store: Any = None) -> None:
        self.config = config
        self.tool_permission_store = tool_permission_store


def _config(*, enabled: bool, endpoints: list[str] | None = None) -> SystemConfig:
    return SystemConfig(
        federation=FederationConfig(
            ard=FederationArdConfig(enabled=enabled, discovery_endpoints=endpoints or [])
        )
    )


def _client(runtime: _Runtime) -> TestClient:
    from probos.routers.ard import router

    app = FastAPI()
    app.include_router(router)
    app.state.runtime = runtime
    return TestClient(app)


def test_discovered_gate_off_returns_404() -> None:
    resp = _client(_Runtime(_config(enabled=False))).get("/ard/discovered")
    assert resp.status_code == 404
    assert resp.json()["detail"] == "feature_disabled"


def test_discovered_enabled_empty_endpoints_honest_degrade() -> None:
    # enabled + zero configured endpoints → 200 with an empty discovered list
    # (no outbound network).
    resp = _client(_Runtime(_config(enabled=True, endpoints=[]))).get("/ard/discovered")
    assert resp.status_code == 200
    body = resp.json()
    assert body["specVersion"] == "1.0"
    assert body["conformance"] == "registry"
    assert body["discovered"] == []


def test_access_gate_off_returns_404() -> None:
    resp = _client(_Runtime(_config(enabled=False))).post(
        "/ard/agents/agent-1/access", json={"catalog": "cat", "resource": "res"}
    )
    assert resp.status_code == 404


def test_access_grant_and_list_roundtrip() -> None:
    store = ToolPermissionStore(db_path="")
    client = _client(_Runtime(_config(enabled=True), tool_permission_store=store))

    post = client.post(
        "/ard/agents/agent-1/access",
        json={"catalog": "cat", "resource": "res", "enabled": True},
    )
    assert post.status_code == 200
    body = post.json()
    assert body["tool_id"] == "ard:cat:res"
    assert body["enabled"] is True
    assert body["is_restriction"] is False
    assert body["grant_id"]

    listed = client.get("/ard/agents/agent-1/access")
    assert listed.status_code == 200
    grants = listed.json()["grants"]
    assert {"tool_id": "ard:cat:res", "is_restriction": False} in grants


def test_access_disable_issues_restriction_then_clear() -> None:
    store = ToolPermissionStore(db_path="")
    client = _client(_Runtime(_config(enabled=True), tool_permission_store=store))

    post = client.post(
        "/ard/agents/agent-1/access",
        json={"catalog": "cat", "resource": "res", "tool": "t", "enabled": False},
    )
    assert post.status_code == 200
    assert post.json()["tool_id"] == "ard:cat:res:t"
    assert post.json()["is_restriction"] is True

    cleared = client.delete("/ard/agents/agent-1/access")
    assert cleared.status_code == 200
    assert cleared.json()["revoked"] >= 1
    # After clear, the agent has no ARD grants left.
    assert client.get("/ard/agents/agent-1/access").json()["grants"] == []


def test_access_store_unavailable_returns_503() -> None:
    client = _client(_Runtime(_config(enabled=True), tool_permission_store=None))
    resp = client.post("/ard/agents/agent-1/access", json={"catalog": "cat", "resource": "res"})
    assert resp.status_code == 503
