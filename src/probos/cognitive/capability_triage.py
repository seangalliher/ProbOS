"""AD-854: Acquire-vs-build capability triage router (grant -> install -> build).

A **pure** decision core (no I/O, deterministic over plain data) plus a thin
async driver that performs all I/O. The pure functions map a capability need to
the cheapest reversible rung, aligned with the three governance axioms:

  - **grant**   -> Minimal Authority      (most reversible, no new code)
  - **install** -> Reversibility Preference (sandboxed, revocable)
  - **build**   -> Safety Budget          (most expensive, always Captain-gated)

The real gap surface is a plain ``str`` (``runtime._last_capability_gap`` / the
unhandled-intent name); the driver resolves it into the three booleans the pure
``triage`` consumes. There is intentionally NO ``CapabilityGap`` dataclass.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from probos.tools.protocol import ToolPermission, permission_includes

if TYPE_CHECKING:
    from probos.capability_request import CapabilityRequest, CapabilityRequestStore
    from probos.config import CapabilityTriageConfig
    from probos.tools.permissions import ToolPermissionStore

logger = logging.getLogger(__name__)

Rung = Literal["grant", "install", "build"]


def triage(
    *,
    tool_registered: bool,
    agent_has_permission: bool,
    skill_known: bool,
) -> Rung:
    """Pick the cheapest reversible rung from three already-resolved booleans.

    1. **grant** — a registered tool the agent lacks permission for
       (``tool_registered and not agent_has_permission``).
    2. **install** — a known skill/extension (``skill_known``).
    3. **build** — otherwise (least reversible; always needs Captain approval).
    """
    if tool_registered and not agent_has_permission:
        return "grant"
    if skill_known:
        return "install"
    return "build"


def evaluate_grant_fast_path(
    *,
    non_destructive: bool,
    peer_precedent: bool,
    agent_trust: float,
    trust_floor: float,
    fast_path_enabled: bool,
) -> bool:
    """Decide whether a ``grant`` rung may be auto-approved without a Captain prompt.

    True only when the fast path is enabled AND the target tool is non-destructive
    AND an in-department peer already holds the grant AND the requesting agent's
    trust is at or above the configured floor. ``install`` and ``build`` never call
    this.
    """
    return (
        fast_path_enabled
        and non_destructive
        and peer_precedent
        and agent_trust >= trust_floor
    )


def _derive_tool_permission(registration: Any) -> ToolPermission:
    """Derive a tool's effective required permission from its default matrix.

    Returns the highest ``ToolPermission`` across the registration's rank
    ``default_permissions`` values. An empty matrix means the ship-wide default
    of READ (per ``ToolRegistration`` semantics).
    """
    defaults = getattr(registration, "default_permissions", None) or {}
    highest = ToolPermission.NONE
    for value in defaults.values():
        try:
            level = ToolPermission(value)
        except ValueError:
            continue
        if permission_includes(level, highest):
            highest = level
    if highest == ToolPermission.NONE:
        return ToolPermission.READ
    return highest


def _is_non_destructive(permission: ToolPermission) -> bool:
    """OBSERVE/READ are non-destructive; WRITE/FULL are destructive."""
    return not permission_includes(permission, ToolPermission.WRITE)


def _agent_has_permission(
    permission_store: ToolPermissionStore | None,
    agent_id: str,
    tool_id: str,
) -> bool:
    """True when the agent holds an active, non-restriction grant for the tool."""
    if permission_store is None:
        return False
    grants = permission_store.get_active_grants_sync(agent_id, tool_id)
    return any(
        not g.is_restriction and g.permission != ToolPermission.NONE for g in grants
    )


def _peer_precedent(
    grants: list[Any],
    *,
    tool_id: str,
    requester_id: str,
    ontology: Any,
) -> bool:
    """True when an in-department peer already holds an active grant for the tool."""
    if ontology is None:
        return False
    req_dept = ontology.get_agent_department(requester_id)
    if req_dept is None:
        return False
    for g in grants:
        if g.tool_id != tool_id or g.is_restriction or g.agent_id == requester_id:
            continue
        holder_dept = ontology.get_agent_department(g.agent_id)
        if holder_dept is not None and holder_dept == req_dept:
            return True
    return False


async def triage_and_file(
    *,
    gap_target: str,
    agent_id: str,
    store: CapabilityRequestStore,
    rationale: str = "",
    work_item_id: str | None = None,
    tool_registry: Any = None,
    permission_store: ToolPermissionStore | None = None,
    extension_registry: Any = None,
    ontology: Any = None,
    trust_network: Any = None,
    self_mod_pipeline: Any = None,
    config: CapabilityTriageConfig | None = None,
) -> CapabilityRequest:
    """Resolve a capability gap to a rung, file the request, and route fulfilment.

    Gathers the three booleans from the live registries, calls the pure ``triage``,
    files a :class:`CapabilityRequest` (AD-853, carrying ``work_item_id``), and on
    approval routes to the existing fulfiller for that rung:

      - **grant** — auto-approved when the grant fast path passes, then issued via
        ``ToolPermissionStore.issue_grant`` and marked fulfilled; otherwise left
        pending for the Captain.
      - **install** — always left pending for Captain approval (no fast path).
      - **build** — routed to ``self_mod_pipeline.handle_unhandled_intent`` which
        owns its own approval gate; marked fulfilled on a successful build.

    Honest-degrades to ``build`` (logged) when the registries needed to resolve a
    cheaper rung are absent.
    """
    tool_reg = tool_registry.get(gap_target) if tool_registry is not None else None
    tool_registered = tool_reg is not None
    has_permission = _agent_has_permission(permission_store, agent_id, gap_target)
    skill_known = (
        extension_registry is not None
        and extension_registry.get_manifest(gap_target) is not None
    )

    if tool_registry is None and extension_registry is None:
        logger.warning(
            "AD-854: triage for %r has no tool/extension registry; "
            "honest-degrading toward build",
            gap_target,
        )

    kind = triage(
        tool_registered=tool_registered,
        agent_has_permission=has_permission,
        skill_known=skill_known,
    )

    req = await store.file_request(
        agent_id=agent_id,
        kind=kind,
        target=gap_target,
        rationale=rationale,
        work_item_id=work_item_id,
    )
    logger.info(
        "AD-854: triaged %r for %s -> %s (request %s)",
        gap_target, agent_id, kind, req.id[:12],
    )

    if kind == "grant":
        return await _route_grant(
            req,
            store=store,
            agent_id=agent_id,
            tool_id=gap_target,
            tool_registration=tool_reg,
            permission_store=permission_store,
            ontology=ontology,
            trust_network=trust_network,
            config=config,
        )
    if kind == "build":
        return await _route_build(
            req,
            store=store,
            gap_target=gap_target,
            rationale=rationale,
            self_mod_pipeline=self_mod_pipeline,
        )
    # install: always Captain-gated — leave pending.
    return req


async def _route_grant(
    req: CapabilityRequest,
    *,
    store: CapabilityRequestStore,
    agent_id: str,
    tool_id: str,
    tool_registration: Any,
    permission_store: ToolPermissionStore | None,
    ontology: Any,
    trust_network: Any,
    config: CapabilityTriageConfig | None,
) -> CapabilityRequest:
    """Evaluate the grant fast path; auto-approve + issue + fulfil when it passes."""
    permission = _derive_tool_permission(tool_registration)
    non_destructive = _is_non_destructive(permission)

    grants: list[Any] = []
    if permission_store is not None:
        grants = await permission_store.list_grants(active_only=True)
    peer_precedent = _peer_precedent(
        grants, tool_id=tool_id, requester_id=agent_id, ontology=ontology
    )

    agent_trust = trust_network.get_score(agent_id) if trust_network is not None else 0.0
    fast_path_enabled = config.grant_fast_path_enabled if config is not None else False
    trust_floor = config.grant_trust_floor if config is not None else 1.0

    auto = evaluate_grant_fast_path(
        non_destructive=non_destructive,
        peer_precedent=peer_precedent,
        agent_trust=agent_trust,
        trust_floor=trust_floor,
        fast_path_enabled=fast_path_enabled,
    )
    logger.info(
        "AD-854: grant fast-path for %s on %s -> %s "
        "(non_destructive=%s, peer_precedent=%s, trust=%.3f>=%.3f, enabled=%s)",
        agent_id, tool_id, auto, non_destructive, peer_precedent,
        agent_trust, trust_floor, fast_path_enabled,
    )
    if not auto:
        return req

    if permission_store is None:
        logger.warning(
            "AD-854: grant fast-path passed for %s on %s but no permission store; "
            "leaving request %s pending",
            agent_id, tool_id, req.id[:12],
        )
        return req

    await store.decide(
        req.id,
        approve=True,
        reason="grant fast-path: non-destructive + in-dept peer precedent + trust>=floor",
        decided_by="capability_triage",
    )
    await permission_store.issue_grant(
        agent_id,
        tool_id,
        permission,
        reason="AD-854 grant fast-path auto-approval",
        issued_by="capability_triage",
    )
    return await store.mark_fulfilled(req.id) or req


async def _route_build(
    req: CapabilityRequest,
    *,
    store: CapabilityRequestStore,
    gap_target: str,
    rationale: str,
    self_mod_pipeline: Any,
) -> CapabilityRequest:
    """Route a build rung to the self-modification pipeline (own approval gate)."""
    if self_mod_pipeline is None:
        logger.warning(
            "AD-854: build triaged for %r but no self-mod pipeline; "
            "leaving request %s pending",
            gap_target, req.id[:12],
        )
        return req
    record = await self_mod_pipeline.handle_unhandled_intent(
        gap_target,
        rationale or f"Capability gap: {gap_target}",
        {},
    )
    if record is not None and getattr(record, "status", None) == "active":
        return await store.mark_fulfilled(req.id) or req
    return req
