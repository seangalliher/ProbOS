"""AD-889 commissioning chain: Role -> Skills -> Tools, for one agent.

BF-906 (#1594) moved this out of ``probos.acm.AgentCapitalService.commission``
with no behaviour change. The chain composes runtime services (the skill service,
ontology, tool registry, permission store and skill registry) and holds no ACM
state. ``AgentCapitalService.commission`` stays the one front door and delegates
here, so its callers (the Captain's routes and the BF-906 crew enroller) are
unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


async def commission_chain(
    agent_id: str, agent_type: str, runtime: Any,
    *, preserve_existing: bool = False, grant_issued_by: str = "captain",
) -> dict[str, Any]:
    """AD-889: Walk the capability spine Role → Skills → Tools at commissioning.

    Composes three subsystems into a single front door: (1) the AD-428 skill
    service assigns PCCs + legacy role skills, (2) the ontology RoleTemplate's
    required skills are acquired at their declared proficiency (preferred over
    the legacy dict), and (3) each acquired skill's preferred tools — resolved
    via the AD-888 resolver — are granted to the agent. Each step
    honest-degrades (Tier-2 log-and-degrade) so a missing subsystem never
    aborts commissioning. Re-commission is idempotent: ``acquire_skill``
    upserts and an existing active grant is skipped.
    """
    summary: dict[str, Any] = {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "skills_acquired": [],
        "tools_granted": [],
    }

    skill_service = getattr(runtime, "skill_service", None)
    if skill_service is None:
        logger.debug(
            "AD-889: skill_service absent — commission skipped for %s", agent_id,
        )
        return summary

    # BF-906: through the crew enroller, keep every skill record the agent held
    # before this commissioning (proficiency, exercise count, history). The
    # snapshot comes first, so this commissioning's own PCC -> template upgrade
    # still applies.
    preserved: frozenset[str] = frozenset()
    if preserve_existing:
        try:
            before = await skill_service.get_profile(agent_id)
        except Exception:
            logger.warning(
                "BF-906: pre-commission profile read failed for %s; commission "
                "skipped so no existing skill record is overwritten",
                agent_id, exc_info=True,
            )
            return summary
        preserved = frozenset(r.skill_id for r in before.all_skills)

    # 1. PCCs + legacy role skills (AD-428 commission_agent).
    try:
        await skill_service.commission_agent(
            agent_id, agent_type, skip_skill_ids=preserved,
        )
    except Exception:
        logger.debug(
            "AD-889: base commission_agent failed for %s", agent_id, exc_info=True,
        )

    # 2. Role → Skills via the ontology RoleTemplate, preferred over the legacy
    #    dict. SkillRequirement.min_proficiency is a raw int (1-7) → ProficiencyLevel.
    ontology = getattr(runtime, "ontology", None)
    template = ontology.get_role_template_for_agent(agent_type) if ontology else None
    if template is not None:
        from probos.skill_framework import ProficiencyLevel
        for req in template.required_skills:
            if req.skill_id in preserved:
                continue
            try:
                level = ProficiencyLevel(req.min_proficiency)
            except ValueError:
                level = ProficiencyLevel.FOLLOW
            try:
                await skill_service.acquire_skill(
                    agent_id, req.skill_id, source="commission", proficiency=level,
                )
            except ValueError:
                # Prerequisite not met at commissioning — expected for chained skills.
                logger.debug(
                    "AD-889: skill %s prereq unmet for %s — skipped",
                    req.skill_id, agent_id,
                )

    # Fetch the post-acquisition profile once (skill_service is present here).
    profile = None
    try:
        profile = await skill_service.get_profile(agent_id)
        summary["skills_acquired"] = [r.skill_id for r in profile.all_skills]
    except Exception:
        logger.debug(
            "AD-889: profile fetch failed for %s", agent_id, exc_info=True,
        )

    # 3. Skills → Tools via the AD-888 resolver + permission grants. Requires the
    #    tool registry (resolution), the permission store (grants), and the skill
    #    registry (skill definitions); any absent → honest-degrade, no grants.
    tool_permission_store = getattr(runtime, "tool_permission_store", None)
    tool_registry = getattr(runtime, "tool_registry", None)
    skill_registry = getattr(runtime, "skill_registry", None)
    if (
        profile is not None
        and tool_permission_store is not None
        and tool_registry is not None
        and skill_registry is not None
    ):
        from probos.tools.protocol import ToolPermission
        from probos.tools.skill_tool_resolver import resolve_tools_for_skill
        try:
            for record in profile.all_skills:
                skill_def = skill_registry.get_skill(record.skill_id)
                if skill_def is None:
                    continue
                regs = resolve_tools_for_skill(
                    skill_def, agent_id=agent_id, tool_registry=tool_registry,
                )
                for reg in regs:
                    # Idempotent + AD-1009 override-preserving: skip if ANY
                    # active per-agent decision exists for this tool — a grant
                    # OR a manual Captain restriction. Re-applying a role
                    # template (apply-role) must never clobber a per-agent
                    # override (agent-precedence). At birth there are no
                    # decisions, so this is byte-identical to the first
                    # commission; only re-apply benefits.
                    existing = tool_permission_store.get_active_grants_sync(
                        agent_id, reg.tool_id,
                    )
                    if existing:
                        continue
                    await tool_permission_store.issue_grant(
                        agent_id, reg.tool_id, ToolPermission.READ,
                        is_restriction=False, reason="commission",
                        issued_by=grant_issued_by,
                    )
                    summary["tools_granted"].append(reg.tool_id)
        except Exception:
            logger.debug(
                "AD-889: tool grant step failed for %s", agent_id, exc_info=True,
            )

    return summary
