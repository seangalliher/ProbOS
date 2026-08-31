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
    2. **install** — a registered-but-disabled MCP server (``skill_known``).
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


def resolve_installable_mcp_server(
    mcp_server_store: Any,
    gap_target: str,
) -> Any | None:
    """AD-1215: the registered-but-disabled MCP server an ``install`` would enable.

    This is the whole meaning of the ``install`` rung (#1205): a server the ship
    already knows about, matched by id or by name, that is currently switched off.
    An already-enabled server is deliberately **not** installable — the capability
    is present, so the cheaper ``grant``/``build`` reasoning should stand instead
    of filing an install that would be a no-op.

    Matching is two-stage: an **exact id match wins over a name match**, because
    an id is unique (uuid4 + ``PRIMARY KEY``, and ``update`` refuses to change it)
    whereas a name is only unique within its own column and may equal some other
    record's id. Within the winning axis, a disabled candidate is returned if one
    exists, so an enabled record cannot mask a later installable one; ties fall to
    store order, which ``list_sync`` reports deterministically (creation order).

    Returns ``None`` when the store is absent, unreadable, or holds no match, and
    when every candidate on the winning axis is already enabled.
    """
    if mcp_server_store is None:
        return None
    try:
        records = mcp_server_store.list_sync()
    except Exception:
        logger.warning(
            "AD-1215: mcp_server_store.list_sync() failed while resolving %r; "
            "treating it as no installable server so triage falls through to build",
            gap_target,
            exc_info=True,
        )
        return None
    by_id = [r for r in records if getattr(r, "id", None) == gap_target]
    matched = by_id or [r for r in records if getattr(r, "name", None) == gap_target]
    for rec in matched:
        if not getattr(rec, "enabled", False):
            return rec
    return None


_DESIGN_CONTEXT_KEYS = (
    "intent_description",
    "parameters",
    "requires_consensus",
    "execution_context",
)


def _build_payload(design_context: dict[str, Any] | None) -> dict[str, Any] | None:
    """BF-744: the design context a later approval needs, and nothing else.

    Bounded to four known keys so a caller cannot use the request payload as an
    open side-channel, and so what a Captain approves is what gets designed.
    """
    if not isinstance(design_context, dict):
        return None
    out = {k: design_context[k] for k in _DESIGN_CONTEXT_KEYS if k in design_context}
    return out or None


async def triage_and_file(
    *,
    gap_target: str,
    agent_id: str,
    store: CapabilityRequestStore,
    rationale: str = "",
    work_item_id: str | None = None,
    tool_registry: Any = None,
    permission_store: ToolPermissionStore | None = None,
    mcp_server_store: Any = None,
    ontology: Any = None,
    trust_network: Any = None,
    self_mod_pipeline: Any = None,
    design_context: dict[str, Any] | None = None,
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
    # AD-1215: the install rung means "enable a registered MCP server". It used to
    # ask an ``extension_registry`` that no runtime ever assigned, so skill_known
    # was unconditionally False and this rung could never be selected.
    skill_known = resolve_installable_mcp_server(mcp_server_store, gap_target) is not None

    if tool_registry is None and mcp_server_store is None:
        logger.warning(
            "AD-854: triage for %r has no tool/MCP registry; "
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
        # BF-744: the design context rides on the request so a build reached
        # LATER, through Captain approval, is designed with the same governance
        # properties as one built at file time. Without it, approving a pending
        # build produced an agent with requires_consensus=False regardless of
        # what the gap actually asked for.
        payload=_build_payload(design_context) if kind == "build" else None,
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
            design_context=design_context,
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
    return await fulfil_grant(
        req.id,
        store=store,
        agent_id=agent_id,
        tool_id=tool_id,
        tool_registration=tool_registration,
        permission_store=permission_store,
        reason="AD-854 grant fast-path auto-approval",
        issued_by="capability_triage",
    ) or req


async def _route_build(
    req: CapabilityRequest,
    *,
    store: CapabilityRequestStore,
    gap_target: str,
    rationale: str,
    self_mod_pipeline: Any,
    design_context: dict[str, Any] | None = None,
) -> CapabilityRequest:
    """Route a build rung to the self-modification pipeline (own approval gate)."""
    return await fulfil_build(
        req.id,
        store=store,
        gap_target=gap_target,
        rationale=rationale,
        self_mod_pipeline=self_mod_pipeline,
        design_context=design_context,
    ) or req


# ── The fulfillers: what an approved rung actually DOES ────────────────────
#
# AD-1211. These are the *performing* half, split out from the *evaluating*
# half above so the two callers share one description of each rung:
#
#   * the file-time fast path in this module, when triage auto-approves; and
#   * ``routers/capability_requests._maybe_fulfil_on_approval``, when the
#     Captain approves a request that was left pending.
#
# Only the first caller existed before AD-1211, so approving a pending grant,
# install or build recorded the decision and did nothing else — no grant
# issued, no FULFILLED event, and ``CapabilityGapDriver`` (which resumes on
# FULFILLED only) left the linked work item blocked forever.
#
# Each returns the fulfilled request, or ``None`` when it could not fulfil.
# A ``None`` return must mean ``mark_fulfilled`` was NOT called, so the caller
# reports the failure honestly and the Captain can retry it (BF-722).


async def fulfil_grant(
    request_id: str,
    *,
    store: CapabilityRequestStore,
    agent_id: str,
    tool_id: str,
    tool_registration: Any,
    permission_store: ToolPermissionStore | None,
    reason: str,
    issued_by: str,
) -> CapabilityRequest | None:
    """Issue the tool grant an approved ``grant`` request asked for, then fulfil it.

    The permission is derived from the tool's own default matrix rather than
    supplied by the caller, so neither path can grant wider access than the
    tool declares it needs (Minimal Authority). Returns ``None`` without
    marking fulfilled when there is no permission store to issue into.
    """
    if permission_store is None:
        logger.warning(
            "AD-1211: cannot fulfil grant request %s for %s on %s — no tool "
            "permission store is wired; the approval is recorded but no grant "
            "was issued and any work item blocked on it stays blocked",
            request_id[:12], agent_id, tool_id,
        )
        return None
    permission = _derive_tool_permission(tool_registration)
    await permission_store.issue_grant(
        agent_id,
        tool_id,
        permission,
        reason=reason,
        issued_by=issued_by,
    )
    return await store.mark_fulfilled(request_id)


async def fulfil_build(
    request_id: str,
    *,
    store: CapabilityRequestStore,
    gap_target: str,
    rationale: str,
    self_mod_pipeline: Any,
    design_context: dict[str, Any] | None = None,
) -> CapabilityRequest | None:
    """Run the self-mod pipeline for an approved ``build`` request, then fulfil it.

    Only an ``active`` record counts as built. The pipeline owns its own
    approval gate and its own failure modes, so anything else — ``None``, or a
    record that was rejected or never activated — leaves the request
    approved-and-unfulfilled and therefore retriable, rather than announcing an
    agent that does not exist.

    BF-744: ``design_context`` carries the four things this call used to drop.
    It passed three positionals — name, rationale, ``{}`` — so
    ``requires_consensus`` took its ``False`` default and every agent designed
    through the capability ladder shipped WITHOUT a consensus gate, however
    destructive the gap was. That contradicts the standing rule that destructive
    intents must set ``requires_consensus=True``. Absent context reproduces the
    old call exactly, so a caller that has none is unchanged.
    """
    if self_mod_pipeline is None:
        logger.warning(
            "AD-1211: cannot fulfil build request %s for %r — no self-mod "
            "pipeline is wired; the approval is recorded but nothing was built "
            "and any work item blocked on it stays blocked",
            request_id[:12], gap_target,
        )
        return None
    ctx = design_context if isinstance(design_context, dict) else {}
    params = ctx.get("parameters")
    record = await self_mod_pipeline.handle_unhandled_intent(
        gap_target,
        str(ctx.get("intent_description") or rationale
            or f"Capability gap: {gap_target}"),
        params if isinstance(params, dict) else {},
        requires_consensus=bool(ctx.get("requires_consensus", False)),
        execution_context=str(ctx.get("execution_context") or ""),
    )
    status = getattr(record, "status", None) if record is not None else None
    if status != "active":
        logger.warning(
            "AD-1211: build for %r (request %s) produced no active agent "
            "(status=%r); the approval stands, the request is not fulfilled "
            "and can be retried",
            gap_target, request_id[:12], status,
        )
        return None
    return await store.mark_fulfilled(request_id)


async def fulfil_install(
    request_id: str,
    *,
    store: CapabilityRequestStore,
    target: str,
    runtime: Any,
) -> CapabilityRequest | None:
    """Install what an approved ``install`` request asked for, then fulfil it.

    Two targets, resolved in that order:

    1. **A registered-but-disabled MCP server** (AD-1215 / #1205) — the rung's
       actual meaning. Enabled in place via ``McpServerStore.set_enabled``, which
       persists the flip. Selection and fulfilment now agree; before AD-1215 the
       rung was *selected* on an extension manifest and *satisfied* by a pip
       install of the same name, so approving one would have installed something
       unrelated.
    2. **A Python dependency** — delegated to ``runtime.ensure_dependency``
       (AD-838c) with ``pre_approved=True``, because the Captain has just approved
       this exact request and must not be asked for it a second time.

    Returns ``None`` without marking fulfilled when neither actor can satisfy the
    target or the install did not succeed.

    There is no file-time caller: triage leaves every ``install`` rung pending
    for the Captain, so unlike ``fulfil_grant`` / ``fulfil_build`` this one is
    reached from the approval path alone.
    """
    server = resolve_installable_mcp_server(
        getattr(runtime, "mcp_server_store", None), target
    )
    if server is not None:
        enabled = await runtime.mcp_server_store.set_enabled(server.id, True)
        if enabled is None:
            logger.warning(
                "AD-1215: enabling MCP server %r for request %s returned no record; "
                "the approval stands, the request is not fulfilled and can be retried",
                target, request_id[:12],
            )
            return None
        # The bridge registration that makes it callable without a restart is
        # #1205's shared register_record() helper; until that lands the boot
        # seed loop picks this up on the next start.
        logger.info(
            "AD-1215: enabled MCP server %s (%s) for approved install request %s",
            enabled.id, enabled.name, request_id[:12],
        )
        return await store.mark_fulfilled(request_id)

    ensure = getattr(runtime, "ensure_dependency", None)
    if not callable(ensure):
        logger.warning(
            "AD-1211: cannot fulfil install request %s for %r — no registered "
            "MCP server matched and the runtime exposes no ensure_dependency; "
            "the approval is recorded but nothing was installed and any blocked "
            "work item stays blocked",
            request_id[:12], target,
        )
        return None
    result = await ensure(target, pre_approved=True)
    if not getattr(result, "success", False):
        logger.warning(
            "AD-1211: installing %r for request %s did not succeed (%s); the "
            "approval stands, the request is not fulfilled and can be retried",
            target, request_id[:12],
            getattr(result, "error", None) or "no error reported",
        )
        return None
    return await store.mark_fulfilled(request_id)
