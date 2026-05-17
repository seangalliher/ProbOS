"""AD-720b: in-chat tool capability grant endpoint — boundary tests.

Uses a real ``ToolPermissionStore`` (in-memory) and a real ``ToolRegistry``
per BF-287 — MagicMock at the substrate boundary is the canonical
anti-pattern. The endpoint is contract-verified against the real
``issue_grant`` signature (NOT a MagicMock-shaped surrogate).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from probos.tools.permissions import ToolPermissionStore
from probos.tools.protocol import ToolPermission


# ── Fakes ───────────────────────────────────────────────────────


def _make_runtime(*, with_registry: bool = True, with_store: bool = True) -> MagicMock:
    runtime = MagicMock()
    agent = MagicMock()
    agent.id = "agent-007"
    agent.agent_type = "engineer"
    agent.pool = "engineering"
    runtime.registry = MagicMock()
    runtime.registry.get.return_value = agent
    runtime.registry.all.return_value = [agent]
    runtime.callsign_registry = MagicMock()
    runtime.callsign_registry.get_callsign.return_value = "Echo"
    runtime.callsign_registry.resolve.return_value = {
        "callsign": "Echo",
        "agent_type": "engineer",
        "agent_id": "agent-007",
        "display_name": "Engineer",
        "department": "engineering",
    }
    runtime.trust_network = MagicMock()
    runtime.trust_network.get_score.return_value = 0.5
    runtime.hebbian_router = MagicMock()
    runtime.hebbian_router.all_weights_typed.return_value = {}
    runtime.intent_bus = MagicMock()
    runtime.intent_bus.send = AsyncMock(return_value=None)
    runtime._start_time = 0.0
    runtime.episodic_memory = None
    runtime.work_item_store = None
    runtime.proactive_loop = None
    runtime.ontology = None
    runtime.add_event_listener = MagicMock()
    runtime.profile_store = None
    runtime.emit_event = MagicMock()

    # Real ToolPermissionStore (in-memory) per BF-287.
    if with_store:
        runtime.tool_permission_store = ToolPermissionStore()
    else:
        runtime.tool_permission_store = None

    if with_registry:
        # Minimal in-memory registry stub that mirrors the .get() shape exactly.
        registered_ids = {"BrowserTool", "mcp:github"}

        class _FakeRegistry:
            def get(self, tool_id):
                return object() if tool_id in registered_ids else None

        runtime.tool_registry = _FakeRegistry()
    else:
        runtime.tool_registry = None

    cfg = MagicMock()
    runtime.config = cfg
    return runtime


def _make_client(runtime: MagicMock) -> TestClient:
    from probos.api import create_app
    return TestClient(create_app(runtime))


# ── Tests ───────────────────────────────────────────────────────


def test_grant_happy_path_persists_grant_with_expiry():
    import time as _time

    runtime = _make_runtime()
    client = _make_client(runtime)
    before = _time.time()
    resp = client.post(
        "/api/chat/tool-grant",
        json={
            "agent_id": "agent-007",
            "tool_id": "BrowserTool",
            "permission": "read",
            "duration_hours": 2,
            "reason": "test grant",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["agent_id"] == "agent-007"
    assert body["tool_id"] == "BrowserTool"
    assert body["permission"] == "read"
    assert body["expires_at"] is not None
    # 2 hours after `before`, within a small tolerance.
    assert before + 2 * 3600 - 5 <= body["expires_at"] <= _time.time() + 2 * 3600 + 5

    # Grant persisted in the store cache.
    grants = runtime.tool_permission_store.get_active_grants_sync("agent-007", "BrowserTool")
    assert len(grants) == 1
    assert grants[0].permission == ToolPermission.READ
    assert grants[0].issued_by == "captain"


def test_grant_no_duration_persists_with_null_expiry():
    runtime = _make_runtime()
    client = _make_client(runtime)
    resp = client.post(
        "/api/chat/tool-grant",
        json={
            "agent_id": "agent-007",
            "tool_id": "BrowserTool",
            "permission": "observe",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["expires_at"] is None


def test_grant_agent_missing_returns_404():
    runtime = _make_runtime()
    runtime.registry.get.return_value = None
    client = _make_client(runtime)
    resp = client.post(
        "/api/chat/tool-grant",
        json={"agent_id": "agent-007", "tool_id": "BrowserTool", "permission": "read"},
    )
    assert resp.status_code == 404


def test_grant_invalid_permission_returns_422_with_valid_enum_list():
    runtime = _make_runtime()
    client = _make_client(runtime)
    resp = client.post(
        "/api/chat/tool-grant",
        json={"agent_id": "agent-007", "tool_id": "BrowserTool", "permission": "rwx"},
    )
    assert resp.status_code == 422
    detail = resp.json()["detail"]
    assert detail["reason"] == "invalid_permission"
    assert "read" in detail["valid"]
    assert "write" in detail["valid"]


def test_grant_tool_not_in_registry_returns_404():
    runtime = _make_runtime()
    client = _make_client(runtime)
    resp = client.post(
        "/api/chat/tool-grant",
        json={"agent_id": "agent-007", "tool_id": "NoSuchTool", "permission": "read"},
    )
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["reason"] == "tool_not_found"


def test_grant_tool_id_accepted_when_registry_absent():
    """When tool_registry is None, the endpoint accepts any non-empty tool_id."""
    runtime = _make_runtime(with_registry=False)
    client = _make_client(runtime)
    resp = client.post(
        "/api/chat/tool-grant",
        json={
            "agent_id": "agent-007",
            "tool_id": "AnythingGoes",
            "permission": "read",
        },
    )
    assert resp.status_code == 200
    assert resp.json()["tool_id"] == "AnythingGoes"


def test_grant_store_missing_returns_503():
    runtime = _make_runtime(with_store=False)
    client = _make_client(runtime)
    resp = client.post(
        "/api/chat/tool-grant",
        json={"agent_id": "agent-007", "tool_id": "BrowserTool", "permission": "read"},
    )
    assert resp.status_code == 503


def test_grant_duration_too_long_returns_422():
    runtime = _make_runtime()
    client = _make_client(runtime)
    resp = client.post(
        "/api/chat/tool-grant",
        json={
            "agent_id": "agent-007",
            "tool_id": "BrowserTool",
            "permission": "read",
            "duration_hours": 1000,
        },
    )
    assert resp.status_code == 422


def test_grant_reason_too_long_returns_422():
    runtime = _make_runtime()
    client = _make_client(runtime)
    resp = client.post(
        "/api/chat/tool-grant",
        json={
            "agent_id": "agent-007",
            "tool_id": "BrowserTool",
            "permission": "read",
            "reason": "x" * 501,
        },
    )
    assert resp.status_code == 422


def test_grant_event_emit_failure_does_not_block_grant():
    """Audit failure must NOT block the grant from being returned (Tier-2 degrade)."""
    runtime = _make_runtime()
    runtime.emit_event = MagicMock(side_effect=RuntimeError("event bus down"))
    client = _make_client(runtime)
    resp = client.post(
        "/api/chat/tool-grant",
        json={"agent_id": "agent-007", "tool_id": "BrowserTool", "permission": "read"},
    )
    assert resp.status_code == 200
    # And the grant was still persisted.
    grants = runtime.tool_permission_store.get_active_grants_sync("agent-007", "BrowserTool")
    assert len(grants) == 1


def test_grant_source_scan_uses_tool_permission_module():
    """AD-720b regression: implementation must import ToolPermission from
    ``probos.tools.protocol`` (single source of truth), not redefine it.
    """
    import inspect

    from probos.routers import chat as _chat_mod

    src = inspect.getsource(_chat_mod.chat_tool_grant)
    assert "from probos.tools.protocol import ToolPermission" in src
    assert "ToolPermissionStore" not in src or "issue_grant" in src
