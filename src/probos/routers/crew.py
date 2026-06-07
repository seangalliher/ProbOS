"""ProbOS API — Crew Personnel routes (AD-892, Crew Personnel Management epic).

Two complementary views of one crew agent that can legitimately drift; the
docstrings below record which surface owns which field:

  - ``GET /api/crew/roster``        — full-crew manning roster. The agent
    *registry* is authoritative for who is aboard (per-instance, includes
    unbilleted crew); the *ontology* manifest is authoritative for org-chart
    facets (post / department / rank).
  - ``GET /api/crew/{id}/record``   — ACM-authoritative consolidated HR record.

Because the roster reads org-chart facets from the ontology and the record
reads role facets from the ACM (CrewProfileStore), department/rank can drift
between the two surfaces. This is intentional and not reconciled here — each
surface reports its own source of truth.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from probos.cognitive import standing_orders
from probos.crew_utils import is_crew_agent
from probos.routers.deps import get_runtime
from probos.tools.protocol import ToolPermission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crew", tags=["crew"])


@router.get("/roster")
async def crew_roster(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Full-crew manning roster reconciled from two sources.

    Sources:
      - ``runtime.registry.all()`` filtered by :func:`is_crew_agent` — the
        authoritative set of who is *aboard* (per-instance). Includes
        unbilleted crew.
      - ``runtime.ontology.get_crew_manifest(...)`` — a by-``agent_type``
        enrichment map for post / department / rank. The manifest *skips*
        agents with no ontology assignment, so it cannot be used alone
        (it would silently drop unbilleted crew).

    Unbilleted agents (registry-present, manifest-absent) carry ``post=None``,
    ``department=None``, ``assigned=False`` and ``billet_state="unbilleted"``
    so the manning gap is visible. Each entry is augmented with
    ``lifecycle_state`` plus cheap ``skill_count`` / ``tool_count``.
    """
    registry = getattr(runtime, "registry", None)
    if registry is None:
        return {"crew": [], "count": 0}

    ontology = getattr(runtime, "ontology", None)
    crew_agents = [a for a in registry.all() if is_crew_agent(a, ontology)]

    # By-agent_type enrichment map from the ontology manifest.
    manifest_by_type: dict[str, dict[str, Any]] = {}
    if ontology is not None:
        try:
            manifest = ontology.get_crew_manifest(
                trust_network=getattr(runtime, "trust_network", None),
                callsign_registry=getattr(runtime, "callsign_registry", None),
            )
            for entry in manifest:
                agent_type = entry.get("agent_type")
                if agent_type:
                    manifest_by_type[agent_type] = entry
        except Exception:
            logger.debug(
                "crew_roster: get_crew_manifest failed; manifest enrichment "
                "skipped, roster degrades to registry facets only",
                exc_info=True,
            )

    acm = getattr(runtime, "acm", None)
    skill_service = getattr(runtime, "skill_service", None)
    tool_perms = getattr(runtime, "tool_permission_store", None)

    entries: list[dict[str, Any]] = []
    for agent in crew_agents:
        agent_type = getattr(agent, "agent_type", None) or ""
        agent_id = getattr(agent, "id", "") or ""
        facets = manifest_by_type.get(agent_type)

        entry: dict[str, Any] = {
            "agent_id": agent_id,
            "agent_type": agent_type,
        }
        if facets is not None:
            entry["callsign"] = facets.get("callsign", "")
            entry["post"] = facets.get("post") or None
            entry["department"] = facets.get("department") or None
            entry["rank"] = facets.get("rank")
            entry["assigned"] = True
            entry["billet_state"] = "billeted"
        else:
            entry["callsign"] = getattr(agent, "callsign", "") or ""
            entry["post"] = None
            entry["department"] = None
            entry["rank"] = None
            entry["assigned"] = False
            entry["billet_state"] = "unbilleted"

        # lifecycle_state — ACM authoritative (async, per-agent).
        if acm is not None and agent_id:
            try:
                state = await acm.get_lifecycle_state(agent_id)
                entry["lifecycle_state"] = state.value
            except Exception:
                logger.debug(
                    "crew_roster: lifecycle fetch failed for %s; omitting field",
                    agent_id, exc_info=True,
                )

        # Cheap skill_count from the skill service profile.
        if skill_service is not None and agent_id:
            try:
                profile = await skill_service.get_profile(agent_id)
                entry["skill_count"] = len(profile.all_skills)
            except Exception:
                logger.debug(
                    "crew_roster: skill_count fetch failed for %s; omitting field",
                    agent_id, exc_info=True,
                )

        # Cheap tool_count — sync, zero I/O. Counts active non-restriction grants.
        if tool_perms is not None and agent_id:
            try:
                grants = tool_perms.get_active_grants_sync(agent_id)
                entry["tool_count"] = sum(1 for g in grants if not g.is_restriction)
            except Exception:
                logger.debug(
                    "crew_roster: tool_count fetch failed for %s; omitting field",
                    agent_id, exc_info=True,
                )

        entries.append(entry)

    entries.sort(key=lambda e: (e["department"] or "~", e["agent_type"]))
    return {"crew": entries, "count": len(entries)}


@router.get("/{agent_id}/record")
async def crew_record(
    agent_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Consolidated crew service record (ACM-authoritative HR view).

    Returns ``runtime.acm.get_consolidated_profile`` augmented with:
      - ``active_assignments`` — open + in_progress work items assigned to
        the agent (from ``runtime.work_item_store``).
      - ``billet`` — the agent's post (title / department) and qualification
        standing (from ``runtime.billet_registry``). Honest-degrades to an
        absent block when the billet registry is unavailable.

    Authority note: this endpoint is ACM-authoritative for the agent's
    consolidated HR record; the roster endpoint is ontology-authoritative for
    org-chart facets. Department/rank may differ between the two surfaces.

    Raises 503 when the ACM is unavailable; 404 when the agent is unknown.
    """
    acm = getattr(runtime, "acm", None)
    if acm is None:
        raise HTTPException(503, "Agent capital service not available")

    registry = getattr(runtime, "registry", None)
    agent_obj = registry.get(agent_id) if registry is not None else None
    if agent_obj is None:
        raise HTTPException(404, f"Agent not found: {agent_id}")

    agent_type = getattr(agent_obj, "agent_type", None) or ""

    profile = await acm.get_consolidated_profile(agent_id, runtime)

    # active_assignments — open + in_progress work items.
    active: list[dict[str, Any]] = []
    store = getattr(runtime, "work_item_store", None)
    if store is not None:
        try:
            items = await store.list_work_items(assigned_to=agent_id, limit=100)
            active = [
                {
                    "id": it.id,
                    "title": it.title,
                    "work_type": it.work_type,
                    "status": it.status,
                    "priority": it.priority,
                }
                for it in items
                if it.status in ("open", "in_progress")
            ]
        except Exception:
            logger.debug(
                "crew_record: work-item fetch failed for %s; "
                "active_assignments degrades to empty",
                agent_id, exc_info=True,
            )
    profile["active_assignments"] = active

    # billet block — post + qualification standing.
    billet_registry = getattr(runtime, "billet_registry", None)
    ontology = getattr(runtime, "ontology", None)
    if billet_registry is not None and agent_type:
        try:
            assignment = (
                ontology.get_assignment_for_agent(agent_type)
                if ontology is not None else None
            )
            post_id = getattr(assignment, "post_id", None) if assignment else None
            if post_id:
                holder = billet_registry.resolve(post_id)
                qualified, missing = await billet_registry.check_qualifications(
                    post_id, agent_type, agent_id,
                )
                profile["billet"] = {
                    "billet_id": post_id,
                    "title": holder.title if holder else None,
                    "department": holder.department if holder else None,
                    "qualified": qualified,
                    "missing_qualifications": missing,
                }
        except Exception:
            logger.debug(
                "crew_record: billet fetch failed for %s; billet block omitted",
                agent_id, exc_info=True,
            )

    return profile


@router.get("/{agent_id}/standing-orders")
async def crew_standing_orders(
    agent_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Read-only four-tier standing orders for a crew agent (AD-893).

    Returns the federation / ship / department / agent tiers separately (the
    personnel record renders them as distinct sections) rather than the merged
    system-prompt string ``compose_instructions`` produces. A tier whose file
    is absent is reported with ``present: False`` rather than omitted. No LLM
    composition and no personality injection — the orders, not the prompt.

    Raises 404 when the agent is unknown.
    """
    registry = getattr(runtime, "registry", None)
    agent_obj = registry.get(agent_id) if registry is not None else None
    if agent_obj is None:
        raise HTTPException(404, f"Agent not found: {agent_id}")

    agent_type = getattr(agent_obj, "agent_type", None) or ""
    tiers = standing_orders.get_order_tiers(agent_type)
    return {"agent_id": agent_id, "agent_type": agent_type, "tiers": tiers}


# ----------------------------------------------------------------------
# Tool certifications (AD-894) — per-agent privilege grants over the audited
# ToolPermissionStore. The ship-wide tool *catalog* lives in routers/tools.py
# (GET /api/tools); these crew-scoped endpoints are personnel-record facets.
# Granting / revoking a tool is a Captain-authority privilege edit, recorded as
# an auditable ToolAccessGrant. No consensus gate (reversible — Minimal
# Authority); the grant-record audit trail is NOT bypassed.
# ----------------------------------------------------------------------


@router.get("/{agent_id}/tools")
async def crew_tool_certifications(
    agent_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """The agent's active tool certifications (AD-894).

    Each active grant from the ``ToolPermissionStore`` is joined with its
    registration metadata from the tool registry (when available). Restrictions
    (``is_restriction``) are included alongside grants so the console can render
    both elevation and reduction; the flag distinguishes them. Honest-degrades
    to an empty list when the permission store is unavailable.
    """
    perms = getattr(runtime, "tool_permission_store", None)
    if perms is None:
        return {"agent_id": agent_id, "certifications": [], "count": 0}
    registry = getattr(runtime, "tool_registry", None)
    certs: list[dict[str, Any]] = []
    for grant in perms.get_active_grants_sync(agent_id):
        meta = registry.get(grant.tool_id) if registry is not None else None
        certs.append({
            "grant_id": grant.id,
            "tool_id": grant.tool_id,
            "permission": grant.permission.value,
            "is_restriction": grant.is_restriction,
            "reason": grant.reason,
            "issued_by": grant.issued_by,
            "issued_at": grant.issued_at,
            "tool": meta.to_dict() if meta is not None else None,
        })
    return {"agent_id": agent_id, "certifications": certs, "count": len(certs)}


@router.post("/{agent_id}/tools")
async def crew_grant_tool(
    agent_id: str,
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Certify (grant) a tool to a crew agent (AD-894).

    Captain-authorized privilege change, recorded as an auditable
    ``ToolAccessGrant``. Body: ``{tool_id, permission, reason?}``.
    """
    perms = getattr(runtime, "tool_permission_store", None)
    if perms is None:
        raise HTTPException(503, "Tool permission store unavailable")
    tool_id = body.get("tool_id")
    permission = body.get("permission")
    if not tool_id or not permission:
        raise HTTPException(400, "tool_id and permission are required")
    registry = getattr(runtime, "tool_registry", None)
    if registry is not None and registry.get(tool_id) is None:
        raise HTTPException(404, f"Tool not found: {tool_id}")
    try:
        perm = ToolPermission(permission)
    except ValueError:
        raise HTTPException(400, f"Invalid permission: {permission}") from None
    grant = await perms.issue_grant(
        agent_id, tool_id, perm,
        reason=body.get("reason", ""), issued_by="captain",
    )
    return {
        "grant_id": grant.id,
        "agent_id": agent_id,
        "tool_id": grant.tool_id,
        "permission": grant.permission.value,
        "reason": grant.reason,
        "issued_by": grant.issued_by,
    }


@router.delete("/{agent_id}/tools/{grant_id}")
async def crew_revoke_tool(
    agent_id: str, grant_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Revoke a tool certification (AD-894). Soft-revoke, retained for audit."""
    perms = getattr(runtime, "tool_permission_store", None)
    if perms is None:
        raise HTTPException(503, "Tool permission store unavailable")
    revoked = await perms.revoke_grant(grant_id)
    if not revoked:
        raise HTTPException(404, f"Grant not found: {grant_id}")
    return {"revoked": True, "grant_id": grant_id, "agent_id": agent_id}
