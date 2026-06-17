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

from collections.abc import Sequence
from dataclasses import dataclass

from probos.tools.protocol import ToolAccessGrant


def mcp_server_tool_id(server_name: str) -> str:
    """Composite ``ToolPermissionStore`` id for server-level (all-tools) access."""
    return f"mcp:{server_name}"


def mcp_tool_tool_id(server_name: str, tool_name: str) -> str:
    """Composite ``ToolPermissionStore`` id for a single tool on a server."""
    return f"mcp:{server_name}:{tool_name}"


@dataclass
class _ScopeFlags:
    """Which (scope × grant/restriction) buckets a grant list lit up."""

    tool_restriction: bool = False
    tool_grant: bool = False
    server_restriction: bool = False
    server_grant: bool = False


def _fold(
    grants: Sequence[ToolAccessGrant], server_id: str, tool_id: str
) -> _ScopeFlags:
    flags = _ScopeFlags()
    for grant in grants:
        if grant.tool_id == tool_id:
            if grant.is_restriction:
                flags.tool_restriction = True
            else:
                flags.tool_grant = True
        elif grant.tool_id == server_id:
            if grant.is_restriction:
                flags.server_restriction = True
            else:
                flags.server_grant = True
    return flags


def resolve_mcp_access(
    grants: list[ToolAccessGrant],
    server_name: str,
    tool_name: str,
    *,
    department_grants: Sequence[ToolAccessGrant] = (),
) -> tuple[bool, str]:
    """Resolve whether ``tool_name`` on ``server_name`` is enabled for an agent.

    Folds the agent's active ``grants`` and the agent's department's
    ``department_grants`` (both already filtered by their stores'
    ``get_active_grants_sync``) into ``(enabled, source)`` where ``source`` is
    one of ``"tool"``, ``"server"``, ``"department"``, or ``"default"``.

    **AD-1019b three-source precedence ladder** (first match wins) — a total,
    deterministic order over (scope-specificity, origin-specificity,
    restriction-first):

    1. agent  tool-scope restriction   → ``(False, "tool")``
    2. agent  tool-scope grant         → ``(True,  "tool")``
    3. dept   tool-scope restriction   → ``(False, "department")``
    4. dept   tool-scope grant         → ``(True,  "department")``
    5. agent  server-scope restriction → ``(False, "server")``
    6. agent  server-scope grant       → ``(True,  "server")``
    7. dept   server-scope restriction → ``(False, "department")``
    8. dept   server-scope grant       → ``(True,  "department")``
    9. (nothing)                       → ``(False, "default")`` (opt-in)

    Tool scope (finer) outranks server scope (broader); within a scope the agent
    (specific) outranks the department (broad); within scope+origin a restriction
    beats a grant. Thus a department's tool-scope restriction can override an
    agent's broad server-scope grant — correct most-specific-match-wins ACL
    semantics.

    **Back-compat (AD-1019a):** ``source`` retains its original three values
    ``{tool, server, default}``; ``"department"`` is purely additive. With
    ``department_grants=()`` (the default) ladder rows 3/4/7/8 are unreachable,
    so the result is byte-identical to the AD-1019 two-source resolver.

    Matching is by exact composite-id equality (kebab-case server names carry no
    colons, so ``mcp:{server}`` and ``mcp:{server}:{tool}`` never collide). An
    empty ``tool_name`` yields the degenerate id ``mcp:{server}:`` which no
    issued grant ever uses, so the resolver cleanly degrades to server scope.
    """
    server_id = mcp_server_tool_id(server_name)
    tool_id = mcp_tool_tool_id(server_name, tool_name)

    a = _fold(grants, server_id, tool_id)
    d = _fold(department_grants, server_id, tool_id)

    if a.tool_restriction:
        return (False, "tool")
    if a.tool_grant:
        return (True, "tool")
    if d.tool_restriction:
        return (False, "department")
    if d.tool_grant:
        return (True, "department")
    if a.server_restriction:
        return (False, "server")
    if a.server_grant:
        return (True, "server")
    if d.server_restriction:
        return (False, "department")
    if d.server_grant:
        return (True, "department")
    return (False, "default")
