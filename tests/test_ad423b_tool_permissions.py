"""AD-423b: Tool Permissions & Scoping tests.

28 tests across 7 classes covering ToolPermission enum, ToolRegistration
extensions, permission resolution chain, check_and_invoke, LOTO locks,
ToolPermissionStore, and /tool-access shell command.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.tools.protocol import (
    Tool,
    ToolAccessGrant,
    ToolPermission,
    ToolRegistration,
    ToolResult,
    ToolType,
    _PERMISSION_ORDER,
    permission_includes,
)
from probos.tools.registry import ToolPermissionDenied, ToolRegistry
from probos.tools.permissions import ToolPermissionStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _StubTool:
    """Minimal Tool protocol implementation for testing."""

    def __init__(
        self,
        tool_id: str = "stub_tool",
        name: str = "Stub Tool",
        tool_type: ToolType = ToolType.INFRA_SERVICE,
        description: str = "A stub tool for testing",
    ) -> None:
        self._tool_id = tool_id
        self._name = name
        self._tool_type = tool_type
        self._description = description
        self._invoke_fn: Any = None

    @property
    def tool_id(self) -> str:
        return self._tool_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def tool_type(self) -> ToolType:
        return self._tool_type

    @property
    def description(self) -> str:
        return self._description

    @property
    def input_schema(self) -> dict[str, Any]:
        return {"type": "object"}

    @property
    def output_schema(self) -> dict[str, Any]:
        return {"type": "string"}

    async def invoke(
        self, params: dict[str, Any], context: dict[str, Any] | None = None
    ) -> ToolResult:
        if self._invoke_fn:
            return await self._invoke_fn(params, context)
        return ToolResult(output="stub_result")


def _make_registry_with_tool(
    tool_id: str = "test_tool",
    department: str | None = None,
    default_permissions: dict[str, str] | None = None,
    restricted_to: list[str] | None = None,
    concurrency: str = "concurrent",
    lock_timeout_seconds: float | None = None,
    enabled: bool = True,
) -> tuple[ToolRegistry, _StubTool]:
    """Create a ToolRegistry with one registered tool."""
    reg = ToolRegistry()
    tool = _StubTool(tool_id=tool_id)
    reg.register(
        tool,
        department=department,
        default_permissions=default_permissions or {},
        restricted_to=restricted_to,
        concurrency=concurrency,
        lock_timeout_seconds=lock_timeout_seconds,
        enabled=enabled,
    )
    return reg, tool


# ===========================================================================
# Class 1: TestToolPermission (3 tests)
# ===========================================================================


class TestToolPermission:
    def test_permission_ordering(self) -> None:
        """NONE < OBSERVE < READ < WRITE < FULL via _PERMISSION_ORDER."""
        perm_list = [ToolPermission.NONE, ToolPermission.OBSERVE, ToolPermission.READ, ToolPermission.WRITE, ToolPermission.FULL]
        for i in range(len(perm_list) - 1):
            assert _PERMISSION_ORDER[perm_list[i]] < _PERMISSION_ORDER[perm_list[i + 1]]

    def test_permission_includes(self) -> None:
        """WRITE includes READ, READ does not include WRITE."""
        assert permission_includes(ToolPermission.WRITE, ToolPermission.READ) is True
        assert permission_includes(ToolPermission.READ, ToolPermission.WRITE) is False
        assert permission_includes(ToolPermission.FULL, ToolPermission.NONE) is True
        assert permission_includes(ToolPermission.NONE, ToolPermission.READ) is False

    def test_permission_enum_values(self) -> None:
        """All 5 values present as str enum."""
        expected = {"none", "observe", "read", "write", "full"}
        actual = {p.value for p in ToolPermission}
        assert actual == expected
        # Confirm str subclass
        assert isinstance(ToolPermission.READ, str)


# ===========================================================================
# Class 2: TestToolRegistrationExtensions (3 tests)
# ===========================================================================


class TestToolRegistrationExtensions:
    def test_default_permissions_field(self) -> None:
        """ToolRegistration default_permissions dict works."""
        tool = _StubTool()
        reg = ToolRegistration(
            tool=tool,
            default_permissions={"ensign": "read", "commander": "write"},
        )
        assert reg.default_permissions["ensign"] == "read"
        assert reg.default_permissions["commander"] == "write"
        d = reg.to_dict()
        assert d["default_permissions"]["ensign"] == "read"

    def test_restricted_to_field(self) -> None:
        """restricted_to list filters correctly."""
        tool = _StubTool()
        reg = ToolRegistration(tool=tool, restricted_to=["agent_a", "agent_b"])
        assert reg.restricted_to == ["agent_a", "agent_b"]
        d = reg.to_dict()
        assert d["restricted_to"] == ["agent_a", "agent_b"]

    def test_concurrency_and_timeout(self) -> None:
        """concurrency='exclusive', lock_timeout_seconds=30.0."""
        tool = _StubTool()
        reg = ToolRegistration(
            tool=tool, concurrency="exclusive", lock_timeout_seconds=30.0,
        )
        assert reg.concurrency == "exclusive"
        assert reg.lock_timeout_seconds == 30.0
        d = reg.to_dict()
        assert d["concurrency"] == "exclusive"
        assert d["lock_timeout_seconds"] == 30.0


# ===========================================================================
# Class 3: TestResolvePermission (6 tests)
# ===========================================================================


class TestResolvePermission:
    def test_disabled_tool_returns_none(self) -> None:
        """Disabled tool → NONE."""
        registry, _ = _make_registry_with_tool(enabled=False)
        perm = registry.resolve_permission("agent_1", "test_tool")
        assert perm == ToolPermission.NONE

    def test_department_mismatch_returns_none(self) -> None:
        """Agent in engineering, tool scoped to security → NONE."""
        registry, _ = _make_registry_with_tool(department="security")
        perm = registry.resolve_permission(
            "agent_1", "test_tool", agent_department="engineering",
        )
        assert perm == ToolPermission.NONE

    def test_restricted_to_excludes(self) -> None:
        """Agent not in restricted_to → NONE."""
        registry, _ = _make_registry_with_tool(restricted_to=["agent_a", "agent_b"])
        perm = registry.resolve_permission("agent_c", "test_tool")
        assert perm == ToolPermission.NONE

    def test_rank_gate_default_matrix(self) -> None:
        """Ensign gets 'read', commander gets 'write' from default_permissions."""
        registry, _ = _make_registry_with_tool(
            default_permissions={"ensign": "read", "commander": "write"},
        )
        perm_ensign = registry.resolve_permission(
            "agent_1", "test_tool", agent_rank="ensign",
        )
        assert perm_ensign == ToolPermission.READ

        perm_commander = registry.resolve_permission(
            "agent_1", "test_tool", agent_rank="commander",
        )
        assert perm_commander == ToolPermission.WRITE

    def test_no_matrix_defaults_to_read(self) -> None:
        """Empty default_permissions → READ for all."""
        registry, _ = _make_registry_with_tool()
        perm = registry.resolve_permission("agent_1", "test_tool")
        assert perm == ToolPermission.READ

    def test_captain_override_grant_up(self) -> None:
        """Captain grant elevates above rank gate."""
        registry, _ = _make_registry_with_tool(
            default_permissions={"ensign": "read"},
        )
        # Create a mock permission store with a grant
        mock_store = MagicMock()
        grant = ToolAccessGrant(
            id="grant_1",
            agent_id="agent_1",
            tool_id="test_tool",
            permission=ToolPermission.WRITE,
            is_restriction=False,
            issued_at=time.time(),
        )
        mock_store.get_active_grants_sync.return_value = [grant]
        registry.set_permission_store(mock_store)

        perm = registry.resolve_permission(
            "agent_1", "test_tool", agent_rank="ensign",
        )
        assert perm == ToolPermission.WRITE


# ===========================================================================
# Class 4: TestCheckAndInvoke (4 tests)
# ===========================================================================


class TestCheckAndInvoke:
    @pytest.mark.asyncio
    async def test_permission_denied_raises(self) -> None:
        """Insufficient permission → ToolPermissionDenied exception."""
        registry, _ = _make_registry_with_tool(
            default_permissions={"ensign": "read"},
        )
        with pytest.raises(ToolPermissionDenied) as exc_info:
            await registry.check_and_invoke(
                "agent_1", "test_tool", {},
                required=ToolPermission.WRITE,
                agent_rank="ensign",
            )
        assert exc_info.value.held == ToolPermission.READ
        assert exc_info.value.required == ToolPermission.WRITE

    @pytest.mark.asyncio
    async def test_permission_denied_emits_event(self) -> None:
        """TOOL_PERMISSION_DENIED event emitted."""
        registry, _ = _make_registry_with_tool(
            default_permissions={"ensign": "read"},
        )
        events: list[tuple[str, dict]] = []
        registry.set_event_callback(lambda t, d: events.append((t, d)))

        with pytest.raises(ToolPermissionDenied):
            await registry.check_and_invoke(
                "agent_1", "test_tool", {},
                required=ToolPermission.WRITE,
                agent_rank="ensign",
            )
        assert len(events) == 1
        assert events[0][0] == "TOOL_PERMISSION_DENIED"
        assert events[0][1]["agent_id"] == "agent_1"

    @pytest.mark.asyncio
    async def test_locked_tool_returns_error(self) -> None:
        """Tool locked by another → ToolResult with error."""
        registry, _ = _make_registry_with_tool(concurrency="exclusive")
        registry.acquire_lock("test_tool", "other_agent", "testing")

        result = await registry.check_and_invoke(
            "agent_1", "test_tool", {},
            required=ToolPermission.READ,
        )
        assert result.success is False
        assert "locked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_successful_invoke(self) -> None:
        """Permission OK + not locked → tool invoked, ToolResult returned."""
        registry, tool = _make_registry_with_tool()
        result = await registry.check_and_invoke(
            "agent_1", "test_tool", {},
            required=ToolPermission.READ,
        )
        assert result.success is True
        assert result.output == "stub_result"


# ===========================================================================
# Class 5: TestLOTO (6 tests)
# ===========================================================================


class TestLOTO:
    def test_acquire_release(self) -> None:
        """Acquire returns True, release returns True, lock cleared."""
        registry, _ = _make_registry_with_tool(concurrency="exclusive")
        assert registry.acquire_lock("test_tool", "agent_1", "work") is True
        assert registry.get_lock("test_tool") is not None
        assert registry.release_lock("test_tool", "agent_1") is True
        assert registry.get_lock("test_tool") is None

    def test_acquire_blocked(self) -> None:
        """Lock held by another → acquire returns False."""
        registry, _ = _make_registry_with_tool(concurrency="exclusive")
        registry.acquire_lock("test_tool", "agent_1")
        assert registry.acquire_lock("test_tool", "agent_2") is False

    def test_acquire_reentrant(self) -> None:
        """Same agent can re-acquire (idempotent)."""
        registry, _ = _make_registry_with_tool(concurrency="exclusive")
        assert registry.acquire_lock("test_tool", "agent_1") is True
        # Same agent re-acquires
        assert registry.acquire_lock("test_tool", "agent_1") is True

    def test_timeout_auto_expire(self) -> None:
        """Expired lock auto-releases on next acquire."""
        registry, _ = _make_registry_with_tool(
            concurrency="exclusive", lock_timeout_seconds=0.001,
        )
        registry.acquire_lock("test_tool", "agent_1")
        # Force lock to be expired by backdating
        registry._locks["test_tool"]["locked_at"] = time.monotonic() - 1.0
        # Now another agent should be able to acquire
        assert registry.acquire_lock("test_tool", "agent_2") is True
        lock = registry.get_lock("test_tool")
        assert lock["holder"] == "agent_2"

    def test_break_lock(self) -> None:
        """Captain break_lock force-releases, emits TOOL_UNLOCKED."""
        registry, _ = _make_registry_with_tool(concurrency="exclusive")
        events: list[tuple[str, dict]] = []
        registry.set_event_callback(lambda t, d: events.append((t, d)))
        registry.acquire_lock("test_tool", "agent_1")

        assert registry.break_lock("test_tool", "Captain override") is True
        assert registry.get_lock("test_tool") is None
        unlock_events = [e for e in events if e[0] == "TOOL_UNLOCKED"]
        assert len(unlock_events) == 1
        assert unlock_events[0][1]["tool_id"] == "test_tool"

    def test_concurrent_tool_rejects_lock(self) -> None:
        """Concurrent tool → acquire returns False."""
        registry, _ = _make_registry_with_tool(concurrency="concurrent")
        assert registry.acquire_lock("test_tool", "agent_1") is False


# ===========================================================================
# Class 6: TestToolPermissionStore (4 tests)
# ===========================================================================


class TestToolPermissionStore:
    @pytest.mark.asyncio
    async def test_issue_and_cache(self) -> None:
        """issue_grant adds to cache (no DB in test mode)."""
        store = ToolPermissionStore()
        await store.start()
        grant = await store.issue_grant(
            agent_id="agent_1",
            tool_id="tool_a",
            permission=ToolPermission.WRITE,
            reason="test grant",
        )
        assert grant.agent_id == "agent_1"
        assert grant.permission == ToolPermission.WRITE
        # Verify in cache
        active = store.get_active_grants_sync("agent_1", "tool_a")
        assert len(active) == 1
        assert active[0].id == grant.id
        await store.stop()

    @pytest.mark.asyncio
    async def test_revoke_soft_delete(self) -> None:
        """revoke_grant removes from cache."""
        store = ToolPermissionStore()
        await store.start()
        grant = await store.issue_grant(
            agent_id="agent_1",
            tool_id="tool_a",
            permission=ToolPermission.READ,
        )
        ok = await store.revoke_grant(grant.id)
        assert ok is True
        active = store.get_active_grants_sync("agent_1", "tool_a")
        assert len(active) == 0
        await store.stop()

    @pytest.mark.asyncio
    async def test_get_active_grants_sync_filters_expired(self) -> None:
        """Sync reads from cache, filters expired."""
        store = ToolPermissionStore()
        await store.start()
        # Issue a grant that is already expired
        await store.issue_grant(
            agent_id="agent_1",
            tool_id="tool_a",
            permission=ToolPermission.READ,
            expires_at=time.time() - 100,  # Already expired
        )
        # Issue a valid grant
        valid = await store.issue_grant(
            agent_id="agent_1",
            tool_id="tool_a",
            permission=ToolPermission.WRITE,
        )
        active = store.get_active_grants_sync("agent_1", "tool_a")
        assert len(active) == 1
        assert active[0].permission == ToolPermission.WRITE
        await store.stop()

    @pytest.mark.asyncio
    async def test_list_grants_active_vs_all(self) -> None:
        """active_only=True excludes revoked, cache list returns all active."""
        store = ToolPermissionStore()
        await store.start()
        g1 = await store.issue_grant(
            agent_id="agent_1",
            tool_id="tool_a",
            permission=ToolPermission.READ,
        )
        await store.issue_grant(
            agent_id="agent_2",
            tool_id="tool_b",
            permission=ToolPermission.WRITE,
        )
        await store.revoke_grant(g1.id)

        # No DB, so list_grants returns cache (which excludes revoked)
        active = await store.list_grants(active_only=True)
        assert len(active) == 1
        assert active[0].agent_id == "agent_2"
        await store.stop()


# ===========================================================================
# Class 7: TestToolAccessCommand (2 tests)
# ===========================================================================


class TestToolAccessCommand:
    @pytest.mark.asyncio
    async def test_cmd_grant_and_list(self) -> None:
        """/tool-access grant followed by /tool-access list shows the grant."""
        from probos.experience.commands.commands_tool_access import (
            cmd_tool_access,
        )

        # Build mock runtime
        runtime = MagicMock()
        console = MagicMock()

        # Mock callsign_registry
        runtime.callsign_registry.resolve.return_value = "agent_worf_1"

        # Mock tool_registry
        tool_reg = ToolRegistry()
        tool = _StubTool(tool_id="phaser_control")
        tool_reg.register(tool)
        runtime.tool_registry = tool_reg

        # Mock tool_permission_store (use real in-memory store)
        store = ToolPermissionStore()
        await store.start()
        runtime.tool_permission_store = store

        # Execute grant
        await cmd_tool_access(runtime, console, "grant Worf phaser_control write 2 tactical need")
        # Verify printed success
        calls = [str(c) for c in console.print.call_args_list]
        assert any("Granted" in c for c in calls)

        # Execute list
        console.print.reset_mock()
        await cmd_tool_access(runtime, console, "list --grants")
        calls = [str(c) for c in console.print.call_args_list]
        assert any("Active grants" in c or "GRANT" in c for c in calls)

        await store.stop()

    @pytest.mark.asyncio
    async def test_cmd_break_lock(self) -> None:
        """/tool-access break-lock releases a held lock."""
        from probos.experience.commands.commands_tool_access import (
            cmd_tool_access,
        )

        runtime = MagicMock()
        console = MagicMock()

        # Set up registry with an exclusive tool and a lock
        tool_reg = ToolRegistry()
        tool = _StubTool(tool_id="warp_core")
        tool_reg.register(tool, concurrency="exclusive")
        tool_reg.acquire_lock("warp_core", "agent_laforge")
        runtime.tool_registry = tool_reg

        assert tool_reg.get_lock("warp_core") is not None

        await cmd_tool_access(runtime, console, "break-lock warp_core engine maintenance")
        assert tool_reg.get_lock("warp_core") is None
        calls = [str(c) for c in console.print.call_args_list]
        assert any("broken" in c.lower() for c in calls)
