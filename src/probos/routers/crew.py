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
from datetime import datetime, timezone
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

        # AD-982a: surface the LIVE vision-capability gate so the personnel
        # ServiceRecord can render + toggle it. Reads the registry profile
        # (reflects boot-applied persistent overrides), not the seed YAML.
        callsign_registry = getattr(runtime, "callsign_registry", None)
        if callsign_registry is not None and agent_type:
            try:
                _vprof = callsign_registry._type_to_profile.get(agent_type, {})
                entry["vision_capable"] = bool(_vprof.get("vision_capable", False))
            except Exception:
                logger.debug(
                    "crew_roster: vision_capable fetch failed for %s; omitting field",
                    agent_id, exc_info=True,
                )

        entries.append(entry)

    entries.sort(key=lambda e: (e["department"] or "~", e["agent_type"]))
    return {"crew": entries, "count": len(entries)}


@router.get("/presence")
async def crew_presence(runtime: Any = Depends(get_runtime)) -> dict[str, Any]:
    """Teams-style per-crew presence — ``offline | online | working | in_meeting``.

    AD-930 aggregates existing signals; it invents no new telemetry:
      - liveness   -> ``agent.is_alive`` (registry ``AgentState`` ACTIVE/DEGRADED)
      - in_meeting -> the agent is a participant of a non-archived chat thread
                      whose ``metadata.meeting_active`` is set (AD-920)
      - working    -> ``agent.meta.last_active`` within
                      ``communications.presence_working_window_seconds`` — an
                      honest *recent-activity* proxy (last completed operation),
                      NOT a true in-flight flag (none exists at HEAD; AD-930a)

    Liveness is the floor: a not-alive agent is ``offline`` regardless of
    thread membership. Among alive agents: ``in_meeting > working > online``.
    Returns ``{"presence": {agent_id: state}, "count": N}`` for crew only.
    """
    registry = getattr(runtime, "registry", None)
    if registry is None:
        return {"presence": {}, "count": 0}

    ontology = getattr(runtime, "ontology", None)
    crew_agents = [a for a in registry.all() if is_crew_agent(a, ontology)]

    # Recency window — comms-config tunable, sensible default, Tier-2 degrade.
    window = 90.0
    try:
        window = float(runtime.config.communications.presence_working_window_seconds)
    except Exception:
        logger.debug("crew_presence: window config unavailable; default 90s", exc_info=True)

    # Meeting participants — Tier-2 degrade: a store failure means no
    # in_meeting is computed and agents simply fall through to working/online.
    meeting_ids: set[str] = set()
    store = getattr(runtime, "chat_thread_store", None)
    if store is not None:
        try:
            for thread in store.list_threads(include_archived=False):
                if (getattr(thread, "metadata", None) or {}).get("meeting_active"):
                    meeting_ids.update(getattr(thread, "participants", None) or [])
        except Exception:
            logger.debug("crew_presence: meeting scan failed; in_meeting skipped", exc_info=True)

    now = datetime.now(timezone.utc)
    presence: dict[str, str] = {}
    for agent in crew_agents:
        agent_id = getattr(agent, "id", "") or ""
        if not agent_id:
            continue
        if not getattr(agent, "is_alive", False):
            presence[agent_id] = "offline"
            continue
        if agent_id in meeting_ids:
            presence[agent_id] = "in_meeting"
            continue
        state = "online"
        meta = getattr(agent, "meta", None)
        last_active = getattr(meta, "last_active", None)
        if last_active is not None:
            try:
                if (now - last_active).total_seconds() < window:
                    state = "working"
            except Exception:
                logger.debug("crew_presence: last_active compare failed for %s", agent_id, exc_info=True)
        presence[agent_id] = state

    return {"presence": presence, "count": len(presence)}


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

    # AD-982a: surface the live vision-capability gate so the personnel
    # ServiceRecord can render + toggle it (reflects boot-applied overrides).
    callsign_registry = getattr(runtime, "callsign_registry", None)
    if callsign_registry is not None and agent_type:
        try:
            _vprof = callsign_registry._type_to_profile.get(agent_type, {})
            profile["vision_capable"] = bool(_vprof.get("vision_capable", False))
        except Exception:
            logger.debug(
                "crew_record: vision_capable fetch failed for %s; omitting field",
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


# ----------------------------------------------------------------------
# Standing-order directives (AD-900) — a thin HTTP surface over the existing
# governed write path (``DirectiveStore``, AD-386). The runtime overlay that
# ``compose_instructions`` merges on top of the immutable four-tier ``.md``
# files. Issuing/approving/revoking is a governed state change; the
# authorization + approval model lives in ``authorize_directive`` /
# ``create_directive`` and is NOT bypassed here. Captain ``CAPTAIN_ORDER``s land
# ACTIVE immediately (existing Minimal-Authority decision); lower-authority
# directives stay PENDING_APPROVAL until ``approve``. No new consensus gate. As
# the ``/order`` CLI does, every mutation calls ``standing_orders.clear_cache()``
# to invalidate the composed-instruction cache.
# ----------------------------------------------------------------------


def _serialize_directive(d: Any) -> dict[str, Any]:
    """Project a :class:`RuntimeDirective` to the personnel-record shape."""
    return {
        "id": d.id,
        "directive_type": d.directive_type.value,
        "content": d.content,
        "status": d.status.value,
        "priority": d.priority,
        "issued_by": d.issued_by,
        "target_department": d.target_department,
    }


@router.get("/{agent_id}/directives")
async def crew_directives(
    agent_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Active + pending-approval directives applicable to a crew agent (AD-900).

    Resolves the agent's ``agent_type`` from the registry, then returns every
    non-inactive directive that targets that type or the ``"*"`` broadcast.
    Includes ``PENDING_APPROVAL`` items so the Captain sees the approval queue.
    Honest-degrades to an empty list when the directive store is unavailable.

    Raises 404 when the agent is unknown.
    """
    registry = getattr(runtime, "registry", None)
    agent_obj = registry.get(agent_id) if registry is not None else None
    if agent_obj is None:
        raise HTTPException(404, f"Agent not found: {agent_id}")
    agent_type = getattr(agent_obj, "agent_type", None) or ""

    store = getattr(runtime, "directive_store", None)
    if store is None:
        return {"agent_id": agent_id, "agent_type": agent_type, "directives": [], "count": 0}

    applicable = [
        d for d in store.all_directives(include_inactive=False)
        if d.target_agent_type == agent_type or d.target_agent_type == "*"
    ]
    directives = [_serialize_directive(d) for d in applicable]
    return {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "directives": directives,
        "count": len(directives),
    }


@router.post("/{agent_id}/directives")
async def crew_issue_directive(
    agent_id: str,
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Issue a Captain's order to a crew agent's type (AD-900).

    Body: ``{content, priority?}``. Mirrors the ``/order`` CLI: a
    ``CAPTAIN_ORDER`` issued at ``Rank.SENIOR`` (Captain authority) lands ACTIVE
    immediately. On success the standing-orders cache is invalidated. Returns
    the authorization ``reason`` as a 400 on failure (e.g. a duplicate order).
    """
    from probos.directive_store import DirectiveType
    from probos.crew_profile import Rank

    store = getattr(runtime, "directive_store", None)
    if store is None:
        raise HTTPException(503, "Directive store unavailable")
    registry = getattr(runtime, "registry", None)
    agent_obj = registry.get(agent_id) if registry is not None else None
    if agent_obj is None:
        raise HTTPException(404, f"Agent not found: {agent_id}")
    agent_type = getattr(agent_obj, "agent_type", None) or ""

    content = body.get("content")
    if not content:
        raise HTTPException(400, "content is required")
    priority = body.get("priority", 5)

    ont = getattr(runtime, "ontology", None)
    department = (
        (ont.get_agent_department(agent_type) if ont is not None else None)
        or standing_orders.get_department(agent_type)
    )

    directive, reason = store.create_directive(
        issuer_type="captain",
        issuer_department=None,
        issuer_rank=Rank.SENIOR,
        target_agent_type=agent_type,
        target_department=department,
        directive_type=DirectiveType.CAPTAIN_ORDER,
        content=content,
        authority=1.0,
        priority=priority,
    )
    if directive is None:
        raise HTTPException(400, reason)
    standing_orders.clear_cache()
    return _serialize_directive(directive)


@router.post("/directives/{directive_id}/approve")
async def crew_approve_directive(
    directive_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Approve a PENDING_APPROVAL directive (AD-900).

    The governed approval gate made visible: promotes a pending lower-authority
    directive to ACTIVE, then invalidates the standing-orders cache. 404 when the
    directive is unknown or not pending.
    """
    store = getattr(runtime, "directive_store", None)
    if store is None:
        raise HTTPException(503, "Directive store unavailable")
    approved = store.approve(directive_id)
    if not approved:
        raise HTTPException(404, f"Directive not found or not pending: {directive_id}")
    standing_orders.clear_cache()
    return {"approved": True, "directive_id": directive_id}


@router.delete("/directives/{directive_id}")
async def crew_revoke_directive(
    directive_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Revoke a directive (AD-900). Soft-revoke, then invalidate the cache."""
    store = getattr(runtime, "directive_store", None)
    if store is None:
        raise HTTPException(503, "Directive store unavailable")
    revoked = store.revoke(directive_id, revoked_by="captain")
    if not revoked:
        raise HTTPException(404, f"Directive not found: {directive_id}")
    standing_orders.clear_cache()
    return {"revoked": True, "directive_id": directive_id}


@router.patch("/directives/{directive_id}")
async def crew_amend_directive(
    directive_id: str,
    body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Amend (FRAGO) a directive's content in place (AD-900), then clear cache.

    Body: ``{content}``. 404 when the directive is unknown or not amendable
    (already revoked/expired).
    """
    store = getattr(runtime, "directive_store", None)
    if store is None:
        raise HTTPException(503, "Directive store unavailable")
    content = body.get("content")
    if not content:
        raise HTTPException(400, "content is required")
    amended = store.amend(directive_id, content, amended_by="captain")
    if amended is None:
        raise HTTPException(404, f"Directive not found or not amendable: {directive_id}")
    standing_orders.clear_cache()
    return _serialize_directive(amended)


# ----------------------------------------------------------------------
# Developmental (T3) skill management (AD-902) — a Captain-facing write
# surface over AgentSkillService (AD-428). Co-located on /api/crew so the
# console fetches one prefix. update_proficiency here is the SAME method the
# /api/skills/.../assess endpoint (AD-428) calls — no logic is duplicated.
# All mutations are reversible (idempotent upsert / two-way level moves /
# soft suspend), so no consensus gate (Minimal Authority).
# ----------------------------------------------------------------------


def _serialize_skill_record(record: Any, defn: Any) -> dict[str, Any]:
    """Project an AgentSkillRecord (+ its definition) to the console shape."""
    data = record.to_dict()
    data["name"] = defn.name if defn is not None else record.skill_id
    data["category"] = defn.category.value if defn is not None else "acquired"
    return data


@router.get("/{agent_id}/skills")
async def crew_developmental_skills(
    agent_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """The agent's developmental (T3) skill records (AD-902).

    Every record — including ``suspended`` ones, so the console can offer
    reinstatement — joined with its registry definition for name + category.
    Honest-degrades to an empty list when the skill service is unavailable.
    """
    skill_service = getattr(runtime, "skill_service", None)
    if skill_service is None:
        return {"agent_id": agent_id, "skills": [], "count": 0}
    registry = getattr(runtime, "skill_registry", None)
    records = await skill_service.get_all_records(agent_id)
    skills = [
        _serialize_skill_record(
            r, registry.get_skill(r.skill_id) if registry is not None else None,
        )
        for r in records
    ]
    return {"agent_id": agent_id, "skills": skills, "count": len(skills)}


@router.post("/{agent_id}/skills")
async def crew_acquire_skill(
    agent_id: str, body: dict[str, Any], runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Give a crew agent a developmental skill (AD-902).

    Body: ``{skill_id, proficiency?, source?}``. ``proficiency`` is the 1-7
    level integer (defaults to FOLLOW=1). Unmet prerequisites raise a 400 with
    the service's explanatory message.
    """
    skill_service = getattr(runtime, "skill_service", None)
    if skill_service is None:
        raise HTTPException(503, "Skill service not available")
    skill_id = body.get("skill_id")
    if not skill_id:
        raise HTTPException(400, "skill_id is required")
    registry = getattr(runtime, "skill_registry", None)
    if registry is not None and registry.get_skill(skill_id) is None:
        raise HTTPException(404, f"Skill not found: {skill_id}")
    from probos.skill_framework import ProficiencyLevel
    level = ProficiencyLevel.FOLLOW
    if "proficiency" in body and body["proficiency"] is not None:
        try:
            level = ProficiencyLevel(int(body["proficiency"]))
        except (ValueError, TypeError):
            raise HTTPException(400, f"Invalid proficiency: {body.get('proficiency')}") from None
    try:
        record = await skill_service.acquire_skill(
            agent_id, skill_id, source=body.get("source", "captain"), proficiency=level,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from None
    defn = registry.get_skill(skill_id) if registry is not None else None
    return _serialize_skill_record(record, defn)


@router.patch("/{agent_id}/skills/{skill_id}")
async def crew_update_skill(
    agent_id: str, skill_id: str, body: dict[str, Any],
    runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Re-level and/or suspend-toggle an agent's skill (AD-902).

    Body may carry ``proficiency`` (1-7 int → ``update_proficiency``) and/or
    ``suspended`` (bool → ``suspend_skill``). Reinstatement is ``{suspended:
    false}``. 404 when the agent holds no record for ``skill_id``.
    """
    skill_service = getattr(runtime, "skill_service", None)
    if skill_service is None:
        raise HTTPException(503, "Skill service not available")
    if "proficiency" not in body and "suspended" not in body:
        raise HTTPException(400, "proficiency or suspended is required")
    from probos.skill_framework import ProficiencyLevel
    record = None
    if "proficiency" in body and body["proficiency"] is not None:
        try:
            level = ProficiencyLevel(int(body["proficiency"]))
        except (ValueError, TypeError):
            raise HTTPException(400, f"Invalid proficiency: {body.get('proficiency')}") from None
        record = await skill_service.update_proficiency(
            agent_id, skill_id, level, source="captain",
            notes=body.get("notes", ""),
        )
        if record is None:
            raise HTTPException(404, f"Agent {agent_id} does not have skill {skill_id}")
    if "suspended" in body and body["suspended"] is not None:
        record = await skill_service.suspend_skill(
            agent_id, skill_id, suspended=bool(body["suspended"]),
        )
        if record is None:
            raise HTTPException(404, f"Agent {agent_id} does not have skill {skill_id}")
    registry = getattr(runtime, "skill_registry", None)
    defn = registry.get_skill(skill_id) if registry is not None else None
    return _serialize_skill_record(record, defn)


@router.delete("/{agent_id}/skills/{skill_id}")
async def crew_suspend_skill(
    agent_id: str, skill_id: str, runtime: Any = Depends(get_runtime),
) -> dict[str, Any]:
    """Suspend a skill (AD-902). Soft, reversible — reinstate via PATCH."""
    skill_service = getattr(runtime, "skill_service", None)
    if skill_service is None:
        raise HTTPException(503, "Skill service not available")
    record = await skill_service.suspend_skill(agent_id, skill_id, suspended=True)
    if record is None:
        raise HTTPException(404, f"Agent {agent_id} does not have skill {skill_id}")
    return {"suspended": True, "agent_id": agent_id, "skill_id": skill_id}
