"""AD-1019: per-agent + per-tool MCP access resolution (pure, no I/O).

The per-agent MCP enablement substrate reuses the audited ``ToolPermissionStore``
(AD-423b / AD-894) with **composite tool ids** instead of a new grant store:

  - server-level (all tools): ``tool_id = f"mcp:{server_name}"``
  - tool-level (one tool):    ``tool_id = f"mcp:{server_name}:{tool_name}"``

``resolve_mcp_access`` is the single pure resolver the router uses to fold a
flat list of active ``ToolAccessGrant`` records into an ``(enabled, source)``
decision for one ``(server, tool)`` pair. It is intentionally free of any store /
bridge / network dependency so it is exhaustively unit-testable.

Precedence (tool-level overrides server-level; restriction beats grant at the
same level): tool-restriction → tool-grant → server-restriction → server-grant →
default. MCP is **opt-in per agent**, so the default is disabled.
"""

from __future__ import annotations

from probos.tools.protocol import ToolAccessGrant


def mcp_server_tool_id(server_name: str) -> str:
    """Composite ``ToolPermissionStore`` id for server-level (all-tools) access."""
    return f"mcp:{server_name}"


def mcp_tool_tool_id(server_name: str, tool_name: str) -> str:
    """Composite ``ToolPermissionStore`` id for a single tool on a server."""
    return f"mcp:{server_name}:{tool_name}"


def resolve_mcp_access(
    grants: list[ToolAccessGrant], server_name: str, tool_name: str
) -> tuple[bool, str]:
    """Resolve whether ``tool_name`` on ``server_name`` is enabled for an agent.

    Folds the agent's active grants (already filtered by the store's
    ``get_active_grants_sync``) into ``(enabled, source)`` where ``source`` is
    ``"tool"``, ``"server"``, or ``"default"``.

    Precedence — tool-level overrides server-level, and a restriction beats a
    grant at the same level:

    1. active tool-level restriction → ``(False, "tool")``
    2. active tool-level grant       → ``(True,  "tool")``
    3. active server-level restriction → ``(False, "server")``
    4. active server-level grant       → ``(True,  "server")``
    5. otherwise                       → ``(False, "default")`` (opt-in)

    Matching is by exact composite-id equality (kebab-case server names carry no
    colons, so ``mcp:{server}`` and ``mcp:{server}:{tool}`` never collide). An
    empty ``tool_name`` yields the degenerate id ``mcp:{server}:`` which no
    issued grant ever uses, so the resolver cleanly degrades to server scope —
    the router relies on this to compute ``server_enabled``.
    """
    server_id = mcp_server_tool_id(server_name)
    tool_id = mcp_tool_tool_id(server_name, tool_name)

    tool_restriction = False
    tool_grant = False
    server_restriction = False
    server_grant = False

    for grant in grants:
        if grant.tool_id == tool_id:
            if grant.is_restriction:
                tool_restriction = True
            else:
                tool_grant = True
        elif grant.tool_id == server_id:
            if grant.is_restriction:
                server_restriction = True
            else:
                server_grant = True

    if tool_restriction:
        return (False, "tool")
    if tool_grant:
        return (True, "tool")
    if server_restriction:
        return (False, "server")
    if server_grant:
        return (True, "server")
    return (False, "default")
