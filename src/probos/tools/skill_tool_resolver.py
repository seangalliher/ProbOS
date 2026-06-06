"""Skill → Tool resolution (AD-888, Skills & Tools Unification epic part 4).

Pure, side-effect-free helper that answers "which tools fulfil this skill?" by
reading the `SkillDefinition.preferred_tools` priority list against the live
`ToolRegistry`, with a capability-tag discovery fallback.

This module only *resolves* — it does not invoke tools, grant permissions, or
mutate any state. The AD-889 commissioning chain (Role → Skills → Tools) calls
this resolver and then grants the returned tools through the permission store.

Layer note: this is a substrate-layer module. It imports `SkillDefinition` from
the foundation-layer `skill_framework` and the tool types from `tools.protocol`
(both downward/same-layer). The optional `hebbian` parameter is type-only via the
``TYPE_CHECKING`` guard so the substrate never imports the mesh layer at runtime.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from probos.skill_framework import SkillDefinition
from probos.tools.protocol import ToolPermission, ToolRegistration
from probos.tools.registry import ToolRegistry

if TYPE_CHECKING:  # pragma: no cover - type-only import to preserve layer discipline
    from probos.mesh.routing import HebbianRouter

logger = logging.getLogger(__name__)


def resolve_tools_for_skill(
    skill: SkillDefinition,
    *,
    agent_id: str,
    tool_registry: ToolRegistry,
    hebbian: "HebbianRouter | None" = None,
) -> list[ToolRegistration]:
    """Resolve the tool registrations that fulfil ``skill`` for ``agent_id``.

    Resolution order:

    1. Honour ``skill.preferred_tools`` in priority order (lower ``priority`` =
       higher), keeping only tools that exist, are enabled, and that the agent has
       at least ``READ`` permission on (``tool_registry.check_permission``).
    2. Capability-tag fallback: when no preferred tool resolves, discover tools by
       the skill's ``domain`` tag via ``tool_registry.list_tools(tag=...)``, again
       permission-filtered.
    3. ``hebbian`` is a documented **no-op** today. The real ranking primitive,
       ``HebbianRouter.get_preferred_targets``, ranks agent→agent compatibility;
       there are no agent→tool edges in the Hebbian graph yet, so there is nothing
       to rank tools by. The parameter is kept so this becomes the activation point
       once agent→tool edges exist.

    Returns an empty list when nothing resolves — never raises for a skill that has
    no fulfilling tools.
    """
    # TODO(AD-888): activate Hebbian tool ranking once agent→tool edges exist in
    # the routing graph. HebbianRouter.get_preferred_targets ranks agent→agent
    # (REL_AGENT) compatibility only, so it cannot rank tools today.
    _ = hebbian  # documented no-op; kept for forward-compatible signature

    resolved: list[ToolRegistration] = []
    seen: set[str] = set()

    # Step 1: preferred tools, in ascending priority order.
    for pref in sorted(skill.preferred_tools, key=lambda p: p.priority):
        if pref.tool_id in seen:
            continue
        reg = tool_registry.get(pref.tool_id)
        if reg is None or not reg.enabled:
            continue
        if not tool_registry.check_permission(agent_id, reg.tool_id, ToolPermission.READ):
            continue
        resolved.append(reg)
        seen.add(reg.tool_id)

    if resolved:
        return resolved

    # Step 2: capability-tag discovery fallback. Only meaningful when the skill
    # declares a concrete domain (not the universal wildcard).
    if skill.domain and skill.domain != "*":
        for reg in tool_registry.list_tools(tag=skill.domain):
            if reg.tool_id in seen:
                continue
            if not tool_registry.check_permission(agent_id, reg.tool_id, ToolPermission.READ):
                continue
            resolved.append(reg)
            seen.add(reg.tool_id)
        if resolved:
            logger.debug(
                "AD-888: skill %s resolved %d tool(s) via domain-tag fallback %r "
                "(no permitted preferred tool)",
                skill.skill_id, len(resolved), skill.domain,
            )

    return resolved
