"""AD-1048: per-agent + per-resource ARD access resolution (pure, no I/O).

DD-3 deny-by-default: ARD resources are OPT-IN per agent. This module MIRRORS
the AD-1019b MCP resolver (``integrations/mcp_bridge/access.py``) EXACTLY — the
same pure ``_fold`` / ``_ScopeFlags`` deny-default precedence ladder — over
composite ``ToolPermissionStore`` ids (so it reuses the audited grant store
rather than building a new one):

  - resource-level (all tools): ``ard:{catalog}:{resource}``
  - tool-level (one tool):      ``ard:{catalog}:{resource}:{tool}``

DD-8 layer discipline: imports ONLY ``ToolAccessGrant`` from
``probos.tools.protocol`` (a leaf — no import cycle). ``resolve_ard_access`` is
store-free and exhaustively unit-testable; ``ard_access_for_agent`` is a thin
store-backed convenience that reads ``get_active_grants_sync`` then folds.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from probos.tools.protocol import ToolAccessGrant


def ard_resource_tool_id(catalog: str, resource: str) -> str:
    """Composite ``ToolPermissionStore`` id for resource-level (all-tools) access."""
    return f"ard:{catalog}:{resource}"


def ard_tool_tool_id(catalog: str, resource: str, tool: str) -> str:
    """Composite ``ToolPermissionStore`` id for a single tool on a resource."""
    return f"ard:{catalog}:{resource}:{tool}"


@dataclass
class _ScopeFlags:
    """Which (scope x grant/restriction) buckets a grant list lit up."""

    tool_restriction: bool = False
    tool_grant: bool = False
    resource_restriction: bool = False
    resource_grant: bool = False


def _fold(
    grants: Sequence[ToolAccessGrant], resource_id: str, tool_id: str
) -> _ScopeFlags:
    flags = _ScopeFlags()
    for grant in grants:
        if grant.tool_id == tool_id:
            if grant.is_restriction:
                flags.tool_restriction = True
            else:
                flags.tool_grant = True
        elif grant.tool_id == resource_id:
            if grant.is_restriction:
                flags.resource_restriction = True
            else:
                flags.resource_grant = True
    return flags


def resolve_ard_access(
    grants: list[ToolAccessGrant],
    catalog: str,
    resource: str,
    tool: str,
    *,
    department_grants: Sequence[ToolAccessGrant] = (),
) -> tuple[bool, str]:
    """Resolve whether ``tool`` on ``catalog/resource`` is enabled for an agent.

    Mirrors AD-1019b ``resolve_mcp_access`` EXACTLY — a total, deterministic
    9-row precedence ladder (first match wins) over
    (scope-specificity, origin-specificity, restriction-first):

    1. agent  tool-scope restriction     → ``(False, "tool")``
    2. agent  tool-scope grant           → ``(True,  "tool")``
    3. dept   tool-scope restriction     → ``(False, "department")``
    4. dept   tool-scope grant           → ``(True,  "department")``
    5. agent  resource-scope restriction → ``(False, "resource")``
    6. agent  resource-scope grant       → ``(True,  "resource")``
    7. dept   resource-scope restriction → ``(False, "department")``
    8. dept   resource-scope grant       → ``(True,  "department")``
    9. (nothing)                         → ``(False, "default")`` (opt-in)

    Tool scope (finer) outranks resource scope (broader); within a scope the
    agent (specific) outranks the department (broad); within scope+origin a
    restriction beats a grant. ARD is opt-in, so the default is disabled.
    ``source`` is one of ``{"tool", "resource", "department", "default"}``.

    Matching is by exact composite-id equality. An empty ``tool`` yields the
    degenerate id ``ard:{catalog}:{resource}:`` which no issued grant ever uses,
    so the resolver cleanly degrades to resource scope.
    """
    resource_id = ard_resource_tool_id(catalog, resource)
    tool_id = ard_tool_tool_id(catalog, resource, tool)

    a = _fold(grants, resource_id, tool_id)
    d = _fold(department_grants, resource_id, tool_id)

    if a.tool_restriction:
        return (False, "tool")
    if a.tool_grant:
        return (True, "tool")
    if d.tool_restriction:
        return (False, "department")
    if d.tool_grant:
        return (True, "department")
    if a.resource_restriction:
        return (False, "resource")
    if a.resource_grant:
        return (True, "resource")
    if d.resource_restriction:
        return (False, "department")
    if d.resource_grant:
        return (True, "department")
    return (False, "default")


def ard_access_for_agent(
    store: Any,
    agent_id: str,
    catalog: str,
    resource: str,
    tool: str | None = None,
    *,
    department_grants: Sequence[ToolAccessGrant] = (),
) -> tuple[bool, str]:
    """Store-backed convenience: read the agent's active grants then resolve.

    Reads ``store.get_active_grants_sync(agent_id)`` (zero-I/O cache read) and
    folds them with ``resolve_ard_access``. A ``None``/empty ``tool`` degrades to
    the degenerate tool id which no issued grant uses, so resolution cleanly
    falls back to resource scope.
    """
    grants = store.get_active_grants_sync(agent_id)
    return resolve_ard_access(
        grants,
        catalog,
        resource,
        tool or "",
        department_grants=department_grants,
    )
