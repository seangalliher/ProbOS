"""AD-1019b: 3-source access resolver tests (agent + department + server-default).

Tests the extended ``resolve_mcp_access`` function that folds agent grants,
department grants, and (future) server-default risk into a single enable/deny.

9-row precedence ladder (most-specific wins):
  1. agent tool-restriction          → (False, "tool")
  2. agent tool-grant                → (True,  "tool")
  3. dept tool-restriction           → (False, "department")
  4. dept tool-grant                 → (True,  "department")
  5. agent server-restriction        → (False, "server")
  6. agent server-grant              → (True,  "server")
  7. dept server-restriction         → (False, "department")
  8. dept server-grant               → (True,  "department")
  9. default (nothing)               → (False, "default")

Run: d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad1019b_resolver_3source.py -q -n 0 -p no:cacheprovider
"""

from __future__ import annotations

import pytest

from probos.integrations.mcp_bridge.access import (
    mcp_server_tool_id,
    mcp_tool_tool_id,
    resolve_mcp_access,
)
from probos.tools.protocol import ToolAccessGrant, ToolPermission


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _tool_grant(
    server_name: str,
    tool_name: str,
    *,
    is_restriction: bool = False,
) -> ToolAccessGrant:
    """Build a tool-scope ToolAccessGrant for testing."""
    return ToolAccessGrant(
        id="test",
        agent_id="agent-or-dept",
        tool_id=mcp_tool_tool_id(server_name, tool_name),
        permission=ToolPermission.READ if not is_restriction else ToolPermission.NONE,
        is_restriction=is_restriction,
        issued_by="test",
        issued_at=0.0,
    )


def _server_grant(
    server_name: str,
    *,
    is_restriction: bool = False,
) -> ToolAccessGrant:
    """Build a server-scope ToolAccessGrant for testing."""
    return ToolAccessGrant(
        id="test",
        agent_id="agent-or-dept",
        tool_id=mcp_server_tool_id(server_name),
        permission=ToolPermission.READ if not is_restriction else ToolPermission.NONE,
        is_restriction=is_restriction,
        issued_by="test",
        issued_at=0.0,
    )


# --------------------------------------------------------------------------- #
# Default (no grants) — MCP is OPT-IN
# --------------------------------------------------------------------------- #


def test_no_grants_default_disabled() -> None:
    """MCP is opt-in: no grants → disabled."""
    enabled, source = resolve_mcp_access([], "weather", "get_forecast")
    assert enabled is False
    assert source == "default"


# --------------------------------------------------------------------------- #
# Agent grants take priority over department grants
# --------------------------------------------------------------------------- #


def test_agent_tool_grant_over_dept_tool_restriction() -> None:
    agent_grants = [_tool_grant("weather", "get_forecast", is_restriction=False)]
    dept_grants = [_tool_grant("weather", "get_forecast", is_restriction=True)]
    enabled, source = resolve_mcp_access(
        agent_grants, "weather", "get_forecast", department_grants=dept_grants
    )
    assert enabled is True
    assert source == "tool"


def test_agent_tool_restriction_over_dept_tool_grant() -> None:
    agent_grants = [_tool_grant("weather", "get_forecast", is_restriction=True)]
    dept_grants = [_tool_grant("weather", "get_forecast", is_restriction=False)]
    enabled, source = resolve_mcp_access(
        agent_grants, "weather", "get_forecast", department_grants=dept_grants
    )
    assert enabled is False
    assert source == "tool"


def test_agent_server_restriction_over_dept_server_grant() -> None:
    agent_grants = [_server_grant("weather", is_restriction=True)]
    dept_grants = [_server_grant("weather", is_restriction=False)]
    # Tool-level query, but server-level grants apply
    enabled, source = resolve_mcp_access(
        agent_grants, "weather", "get_forecast", department_grants=dept_grants
    )
    assert enabled is False
    assert source == "server"


# --------------------------------------------------------------------------- #
# Department grants used when no agent grant covers
# --------------------------------------------------------------------------- #


def test_dept_tool_grant_when_no_agent_grant() -> None:
    dept_grants = [_tool_grant("weather", "get_forecast", is_restriction=False)]
    enabled, source = resolve_mcp_access(
        [], "weather", "get_forecast", department_grants=dept_grants
    )
    assert enabled is True
    assert source == "department"


def test_dept_tool_restriction_when_no_agent_grant() -> None:
    dept_grants = [_tool_grant("weather", "get_forecast", is_restriction=True)]
    enabled, source = resolve_mcp_access(
        [], "weather", "get_forecast", department_grants=dept_grants
    )
    assert enabled is False
    assert source == "department"


def test_dept_server_grant_when_no_agent_grant() -> None:
    dept_grants = [_server_grant("weather", is_restriction=False)]
    enabled, source = resolve_mcp_access(
        [], "weather", "get_forecast", department_grants=dept_grants
    )
    assert enabled is True
    assert source == "department"


def test_dept_server_restriction_when_no_agent_grant() -> None:
    dept_grants = [_server_grant("weather", is_restriction=True)]
    enabled, source = resolve_mcp_access(
        [], "weather", "get_forecast", department_grants=dept_grants
    )
    assert enabled is False
    assert source == "department"


# --------------------------------------------------------------------------- #
# Tool-level beats server-level (within same source)
# --------------------------------------------------------------------------- #


def test_agent_tool_beats_agent_server() -> None:
    # Agent has tool grant, but also server restriction
    agent_grants = [
        _tool_grant("weather", "get_forecast", is_restriction=False),
        _server_grant("weather", is_restriction=True),
    ]
    enabled, source = resolve_mcp_access(agent_grants, "weather", "get_forecast")
    assert enabled is True
    assert source == "tool"


def test_dept_tool_beats_dept_server() -> None:
    dept_grants = [
        _tool_grant("weather", "get_forecast", is_restriction=False),
        _server_grant("weather", is_restriction=True),
    ]
    enabled, source = resolve_mcp_access(
        [], "weather", "get_forecast", department_grants=dept_grants
    )
    assert enabled is True
    assert source == "department"


# --------------------------------------------------------------------------- #
# Mixed chains (realistic governance scenarios)
# --------------------------------------------------------------------------- #


def test_engineering_restricted_but_agent_whitelisted() -> None:
    """
    Scenario: Engineering department is blocked from "run_command" by default,
    but agent "trusted-builder" has an explicit grant for it.
    """
    agent_grants = [_tool_grant("system", "run_command", is_restriction=False)]
    dept_grants = [_tool_grant("system", "run_command", is_restriction=True)]
    enabled, source = resolve_mcp_access(
        agent_grants, "system", "run_command", department_grants=dept_grants
    )
    assert enabled is True
    assert source == "tool"


def test_dept_whitelisted_agent_blacklisted() -> None:
    """
    Scenario: Science department can use weather tools, but a specific agent
    is restricted (e.g., probationary trust).
    """
    agent_grants = [_tool_grant("weather", "get_forecast", is_restriction=True)]
    dept_grants = [_tool_grant("weather", "get_forecast", is_restriction=False)]
    enabled, source = resolve_mcp_access(
        agent_grants, "weather", "get_forecast", department_grants=dept_grants
    )
    assert enabled is False
    assert source == "tool"


def test_no_agent_no_dept_fallback_to_default() -> None:
    """Tools not covered by any grant are disabled by default (opt-in)."""
    enabled, source = resolve_mcp_access(
        [], "unknown_server", "unknown_tool", department_grants=[]
    )
    assert enabled is False
    assert source == "default"


# --------------------------------------------------------------------------- #
# Empty tool_name (server-scope queries via the router)
# --------------------------------------------------------------------------- #


def test_empty_tool_name_uses_server_scope_only() -> None:
    """When tool_name is empty, only server-scope grants should apply."""
    agent_grants = [
        _tool_grant("weather", "get_forecast", is_restriction=True),
        _server_grant("weather", is_restriction=False),
    ]
    # Empty tool_name: should NOT hit the tool-level restriction
    enabled, source = resolve_mcp_access(agent_grants, "weather", "")
    assert enabled is True
    assert source == "server"


# --------------------------------------------------------------------------- #
# Backward compatibility (no department_grants kwarg)
# --------------------------------------------------------------------------- #


def test_backward_compat_no_dept_grants_arg() -> None:
    """Pre-1019b callers don't pass department_grants; should still work."""
    agent_grants = [_tool_grant("weather", "get_forecast", is_restriction=False)]
    # Old signature: resolve_mcp_access(grants, server, tool)
    enabled, source = resolve_mcp_access(agent_grants, "weather", "get_forecast")
    assert enabled is True
    assert source == "tool"
