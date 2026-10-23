"""BF-906 (#1594): one entry point that onboards and commissions a crew member.

AD-427 onboarding (``registered`` -> ``probationary``) and AD-889 commissioning
(Role -> Skills -> Tools) were birth-time hooks that ran only when ACM existed.
Boot crew are wired in Phase 2; ACM, the ontology and the skill service arrive in
Phase 7, so neither hook ran for them. ``CrewEnrollmentService.enroll`` replaces
both hooks and is reached three ways:

* ``enroll_wired_crew``: the Phase 7 pass over every agent wired so far. Source
  ``birth`` when the agent's birth certificate was issued during this boot (or it
  has none), ``backfill`` when the certificate predates the boot.
* ``enroll_joining``: every agent wired after the pass, through
  ``AgentOnboardingService.wire_agent`` (source ``join``), including a visitor who
  becomes crew (AD-1342).

``enroll`` is idempotent: an agent whose state is not ``registered`` is not
onboarded again, an agent with a commissioning record is not commissioned again,
and a commissioning keeps every skill record that existed before it. Trust, rank
and memory are never touched. Commissioning's tool grants cover only tools the
AD-888 resolver already finds readable at ensign level.

BF-917 (#1625): the record keeps a fingerprint of the role template it was
commissioned under. When the template an agent resolves has changed since (a
record written before BF-917 has none, and gaining a template is a change), the
agent is re-commissioned once, keeping every record it holds and without the
Skills -> Tools step, so a re-commission grants no tool.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, replace
from typing import Any

from probos.acm import AgentCapitalService, LifecycleState
from probos.crew_utils import is_crew_agent
from probos.skill_framework import BUILTIN_PCCS

logger = logging.getLogger(__name__)

SOURCE_BIRTH = "birth"
SOURCE_BACKFILL = "backfill"
SOURCE_JOIN = "join"
ENROLLMENT_SOURCES: frozenset[str] = frozenset({SOURCE_BIRTH, SOURCE_BACKFILL, SOURCE_JOIN})

ENROLLMENT_INITIATED_BY = "system"
ENROLLMENT_REASON = "BF-906 (#1594) crew enrollment"
RECOMMISSION_REASON = "BF-917 (#1625) role template changed"
COMMISSIONED_EVENT = "crew_commissioned"
INVARIANT_FAILED_EVENT = "crew_invariant_failed"


@dataclass(frozen=True)
class CrewEnrollment:
    """What one ``enroll`` call did for one crew agent."""
    agent_id: str
    agent_type: str
    source: str
    onboarded: bool
    commissioned: bool
    role_template: str | None = None
    skills_granted: tuple[str, ...] = ()
    tools_granted: tuple[str, ...] = ()
    recommissioned: bool = False  # BF-917: a changed role template was applied to an existing record


@dataclass(frozen=True)
class CrewInvariantReport:
    """BF-906 invariant: every crew agent has a lifecycle row and is commissioned."""
    checked: int
    missing_lifecycle: tuple[str, ...] = ()
    never_commissioned: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.missing_lifecycle and not self.never_commissioned

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "missing_lifecycle": list(self.missing_lifecycle),
            "never_commissioned": list(self.never_commissioned),
        }


def template_fingerprint(template: Any) -> str:
    """BF-917: a digest of what AD-889 commissioning reads from a role template.

    The post id and each required skill's id and floor, in a canonical order: the
    same template always gives the same digest, and any change to what the chain
    would acquire gives a new one. Optional skills are left out because the chain
    reads only ``required_skills``: an optional id that is a PCC or a legacy role
    skill is still acquired, by the chain's base step, but a change to the optional
    list changes nothing the chain does. No template has a digest of its own, so
    gaining or losing a template is a change too.
    """
    if template is None:
        payload: dict[str, Any] = {"post_id": None, "required": []}
    else:
        payload = {
            "post_id": template.post_id,
            "required": sorted([r.skill_id, r.min_proficiency] for r in template.required_skills),
        }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _RecommissionContext:
    """BF-917: the services a template re-commission may use.

    AD-889's chain reads its subsystems from this object by name. It has the skill
    service and the ontology and no ``tool_registry``, ``tool_permission_store`` or
    ``skill_registry``, so the chain's Skills -> Tools step does not run and a
    re-commission grants no tool. Whether that step should grant tools at all is
    the Captain's open question on #1625.
    """

    skill_service: Any
    ontology: Any


async def _has_skills(skill_service: Any, agent_id: str) -> bool:
    if skill_service is None:
        return False
    try:
        profile = await skill_service.get_profile(agent_id)
    except Exception:
        logger.warning("BF-906: skill profile read failed for %s", agent_id, exc_info=True)
        return False
    return bool(profile.all_skills)


async def check_crew_invariant(
    *, acm: AgentCapitalService | None, skill_service: Any, ontology: Any, agents: Iterable[Any],
) -> CrewInvariantReport:
    """Commissioned = a recorded commissioning or a non-empty skill profile.

    An agent ACM records as decommissioned is exempt from the commissioning clause.
    """
    crew = [a for a in agents if is_crew_agent(a, ontology)]
    missing: list[str] = []
    never: list[str] = []
    for agent in crew:
        agent_id = agent.id
        if acm is None:
            missing.append(agent_id)
            never.append(agent_id)
            continue
        if not await acm.has_lifecycle_record(agent_id):
            missing.append(agent_id)
        elif await acm.get_lifecycle_state(agent_id) is LifecycleState.DECOMMISSIONED:
            continue
        if await acm.get_commissioning_record(agent_id) is not None:
            continue
        if await _has_skills(skill_service, agent_id):
            continue
        never.append(agent_id)
    return CrewInvariantReport(
        checked=len(crew),
        missing_lifecycle=tuple(sorted(missing)),
        never_commissioned=tuple(sorted(never)),
    )


async def log_crew_invariant_failure(event_log: Any, report: CrewInvariantReport) -> bool:
    """Write the ``crew_invariant_failed`` event-log row for a failed ``report``.

    Best effort, like the commissioning row: the startup ERROR log and
    ``probos doctor`` are authoritative, so a missing row is never evidence that
    the invariant held. The write lives in this module so that AD-1195's census
    resolves its event from ``INVARIANT_FAILED_EVENT``. Returns True when the row
    was written; False, with a WARNING, when there is no event log or the write
    failed. Never raises.
    """
    if event_log is None:
        logger.warning("BF-906: no event log; the crew invariant failure is in the startup log only")
        return False
    try:
        await event_log.log(
            category="lifecycle", event=INVARIANT_FAILED_EVENT, data=report.to_dict(),
        )
    except Exception:
        logger.warning("BF-906: the invariant failure could not be written to the event log", exc_info=True)
        return False
    return True


class CrewEnrollmentService:
    """BF-906: onboards and commissions crew through one idempotent entry point."""

    def __init__(
        self,
        *,
        acm: AgentCapitalService,
        ontology: Any,
        skill_service: Any,
        identity_registry: Any,
        event_log: Any,
        commission_context: Any,
        boot_started_at: float,
    ) -> None:
        """``commission_context`` is the object AD-889's ``commission`` reads its
        subsystems from (the runtime). ``boot_started_at`` is this boot's wall-clock
        start; it separates ``birth`` from ``backfill``."""
        self._acm = acm
        self._ontology = ontology
        self._skill_service = skill_service
        self._identity_registry = identity_registry
        self._event_log = event_log
        self._commission_context = commission_context
        self._boot_started_at = boot_started_at
        # BF-917 A1: serializes ``enroll`` (see there). One lock per enroller, like ACM's
        # ``_write_lock``; startup builds one enroller. It is always taken outside ACM's lock.
        self._enroll_lock = asyncio.Lock()

    async def enroll(self, agent: Any, *, source: str) -> CrewEnrollment | None:
        """Onboard and commission ``agent`` if it is crew; None for any other agent."""
        if source not in ENROLLMENT_SOURCES:
            raise ValueError(f"BF-906: unknown enrollment source {source!r}")
        if not is_crew_agent(agent, self._ontology):
            return None
        # BF-917 A1: one enrollment at a time. The chain snapshots the profile and then
        # writes each skill it found missing as a fresh record, so two overlapping
        # enrollments of one agent would both acquire it, and the later write would reset
        # a record the earlier one had already advanced. Under the lock the second reads
        # the record the first wrote and finds nothing to do.
        async with self._enroll_lock:
            onboarded = await self._onboard_if_unrecorded(agent, source=source)
            record = await self._acm.get_commissioning_record(agent.id)
            if record is not None:
                return await self._recommission_if_template_changed(
                    agent, record.template_fingerprint, source=source, onboarded=onboarded,
                )
            return await self._commission(agent, source=source, onboarded=onboarded)

    async def enroll_joining(self, agent: Any) -> CrewEnrollment | None:
        """The enroller ``AgentOnboardingService.wire_agent`` calls after the pass."""
        return await self.enroll(agent, source=SOURCE_JOIN)

    async def enroll_wired_crew(self, agents: Iterable[Any]) -> list[CrewEnrollment]:
        """The Phase 7 pass: enroll every agent wired before ACM existed."""
        results: list[CrewEnrollment] = []
        for agent in list(agents):
            try:
                result = await self.enroll(agent, source=self._boot_source(agent))
            except Exception:
                logger.error(
                    "BF-906: enrollment failed for %s (%s); the crew invariant check reports it",
                    getattr(agent, "id", "?"), getattr(agent, "agent_type", "?"), exc_info=True,
                )
                continue
            if result is not None:
                results.append(result)
        logger.info(
            "BF-906: crew enrollment pass: %d crew, %d onboarded, %d commissioned "
            "(%d birth, %d backfill)",
            len(results),
            sum(1 for r in results if r.onboarded),
            sum(1 for r in results if r.commissioned),
            sum(1 for r in results if r.commissioned and r.source == SOURCE_BIRTH),
            sum(1 for r in results if r.commissioned and r.source == SOURCE_BACKFILL),
        )
        return results

    def _boot_source(self, agent: Any) -> str:
        cert = (
            self._identity_registry.get_by_slot(agent.id)
            if self._identity_registry is not None else None
        )
        if cert is not None and cert.birth_timestamp < self._boot_started_at:
            return SOURCE_BACKFILL
        return SOURCE_BIRTH

    def _department(self, agent_type: str) -> str:
        from probos.cognitive.standing_orders import get_department

        dept = self._ontology.get_agent_department(agent_type) if self._ontology is not None else None
        return dept or get_department(agent_type) or "operations"

    async def _onboard_if_unrecorded(self, agent: Any, *, source: str) -> bool:
        if await self._acm.get_lifecycle_state(agent.id) is not LifecycleState.REGISTERED:
            return False
        department = self._department(agent.agent_type)
        try:
            await self._acm.onboard(
                agent_id=agent.id, agent_type=agent.agent_type, pool=agent.pool,
                department=department, initiated_by=ENROLLMENT_INITIATED_BY,
                sovereign_id=getattr(agent, "sovereign_id", "") or "",
                reason=(
                    f"Onboarded as {agent.agent_type} in {department} "
                    f"({ENROLLMENT_REASON}, source={source})"
                ),
            )
        except Exception:
            logger.error(
                "BF-906: ACM onboarding failed for %s (%s); it stays unrecorded and the "
                "crew invariant check reports it", agent.id, agent.agent_type, exc_info=True,
            )
            return False
        return True

    async def _skill_ids(self, agent_id: str) -> list[str] | None:
        try:
            profile = await self._skill_service.get_profile(agent_id)
        except Exception:
            logger.error("BF-906: skill profile read failed for %s", agent_id, exc_info=True)
            return None
        return [r.skill_id for r in profile.all_skills]

    async def _commission(self, agent: Any, *, source: str, onboarded: bool) -> CrewEnrollment:
        agent_id, agent_type = agent.id, agent.agent_type
        not_commissioned = CrewEnrollment(
            agent_id=agent_id, agent_type=agent_type, source=source,
            onboarded=onboarded, commissioned=False,
        )
        if self._skill_service is None:
            logger.error(
                "BF-906: no skill service; %s (%s) cannot be commissioned and the crew "
                "invariant check reports it", agent_id, agent_type,
            )
            return not_commissioned
        before = await self._skill_ids(agent_id)
        if before is None:
            return not_commissioned
        try:
            summary = await self._acm.commission(
                agent_id, agent_type, self._commission_context,
                preserve_existing=True,
                grant_issued_by=ENROLLMENT_INITIATED_BY,
            )
        except Exception:
            logger.error("BF-906: commissioning failed for %s (%s)", agent_id, agent_type, exc_info=True)
            return not_commissioned
        after = await self._skill_ids(agent_id)
        if not after:
            logger.error(
                "BF-906: commissioning left %s (%s) with no skills; not recorded, so the "
                "next boot retries and the crew invariant check reports it", agent_id, agent_type,
            )
            return not_commissioned
        missing_pccs = [pcc.skill_id for pcc in BUILTIN_PCCS if pcc.skill_id not in after]
        if missing_pccs:
            # BF-906 A3: the chain logs a failed base step (AD-428 commission_agent) at
            # DEBUG and carries on, so the enroller checks the result: every crew member
            # holds every PCC. Not recorded, so the next boot retries.
            logger.error(
                "BF-906: commissioning left %s (%s) without the PCCs %s; not recorded, so "
                "the next boot retries", agent_id, agent_type, ", ".join(missing_pccs),
            )
            return not_commissioned
        template = (
            self._ontology.get_role_template_for_agent(agent_type)
            if self._ontology is not None else None
        )
        role_template = template.post_id if template is not None else None
        if role_template is None:
            logger.warning(
                "BF-906: no role template for %s (%s); commissioned with the PCCs and "
                "any legacy role skills only", agent_type, agent_id,
            )
        held_before = set(before)
        skills = tuple(s for s in after if s not in held_before)
        tools = tuple(summary.get("tools_granted", ()))
        reason = f"{ENROLLMENT_REASON}, source={source}"
        recorded = await self._acm.record_commissioning(
            agent_id=agent_id, agent_type=agent_type, source=source,
            role_template=role_template, skills=skills, tools=tools,
            initiated_by=ENROLLMENT_INITIATED_BY, reason=reason,
            template_fingerprint=template_fingerprint(template),
        )
        if recorded:
            await self._log_commissioning(
                agent, source=source, role_template=role_template,
                skills=skills, tools=tools, reason=reason,
            )
        return CrewEnrollment(
            agent_id=agent_id, agent_type=agent_type, source=source, onboarded=onboarded,
            commissioned=recorded, role_template=role_template,
            skills_granted=skills, tools_granted=tools,
        )

    async def _recommission_if_template_changed(
        self, agent: Any, recorded_fingerprint: str | None, *, source: str, onboarded: bool,
    ) -> CrewEnrollment:
        """BF-917: re-run commissioning once when the agent's role template has changed.

        The record's fingerprint (None on a record written before BF-917) is compared
        with the template the ontology resolves now. When they differ, the chain runs
        with ``preserve_existing=True``, so every record the agent holds keeps its
        proficiency, exercise count and history and only skills it lacks are acquired,
        on a context without the tool services, so no tool is granted. The new
        fingerprint is recorded only when the chain returned, read a profile and left
        the agent holding every PCC (the rule ``_commission`` keeps); otherwise nothing
        is recorded and the next enrollment retries. A required skill the chain skips
        because its prerequisite is unmet (AD-889's expected case) does not block the
        record. ``enroll`` holds the enroller's lock around this, so an overlapping
        enrollment of the same agent waits and then finds the fingerprint equal.
        A decommissioned agent is left alone.
        """
        agent_id, agent_type = agent.id, agent.agent_type
        unchanged = CrewEnrollment(
            agent_id=agent_id, agent_type=agent_type, source=source,
            onboarded=onboarded, commissioned=False,
        )
        template = (
            self._ontology.get_role_template_for_agent(agent_type)
            if self._ontology is not None else None
        )
        fingerprint = template_fingerprint(template)
        if recorded_fingerprint == fingerprint:
            return unchanged
        if await self._acm.get_lifecycle_state(agent_id) is LifecycleState.DECOMMISSIONED:
            return unchanged
        if self._skill_service is None:
            logger.error(
                "BF-917: no skill service; the changed role template of %s (%s) is not "
                "applied, and the next boot retries", agent_id, agent_type,
            )
            return unchanged
        before = await self._skill_ids(agent_id)
        if before is None:
            return unchanged
        context = _RecommissionContext(skill_service=self._skill_service, ontology=self._ontology)
        try:
            summary = await self._acm.commission(
                agent_id, agent_type, context,
                preserve_existing=True, grant_issued_by=ENROLLMENT_INITIATED_BY,
            )
        except Exception:
            logger.error(
                "BF-917: re-commissioning failed for %s (%s); the template change is not "
                "recorded, so the next boot retries", agent_id, agent_type, exc_info=True,
            )
            return unchanged
        if not summary.get("skills_acquired"):
            logger.error(
                "BF-917: re-commissioning of %s (%s) read no skill profile; the template "
                "change is not recorded, so the next boot retries", agent_id, agent_type,
            )
            return unchanged
        missing_pccs = [pcc.skill_id for pcc in BUILTIN_PCCS if pcc.skill_id not in summary["skills_acquired"]]
        if missing_pccs:
            # BF-917 A1: the rule a first commissioning keeps (BF-906 A3). The chain logs a
            # failed base step at DEBUG and still returns the profile it read, so a
            # re-commission that left a PCC missing is not recorded, and the next boot retries.
            logger.error(
                "BF-917: re-commissioning left %s (%s) without the PCCs %s; the template change "
                "is not recorded, so the next boot retries", agent_id, agent_type, ", ".join(missing_pccs),
            )
            return unchanged
        held_before = set(before)
        skills = tuple(s for s in summary["skills_acquired"] if s not in held_before)
        role_template = template.post_id if template is not None else None
        recorded = await self._acm.record_commissioning(
            agent_id=agent_id, agent_type=agent_type, source=source,
            role_template=role_template, skills=skills, tools=(),
            initiated_by=ENROLLMENT_INITIATED_BY, reason=f"{RECOMMISSION_REASON}, source={source}",
            template_fingerprint=fingerprint, recommission=True,
        )
        if recorded:
            logger.info(
                "BF-917: re-commissioned %s (%s) under role template %s; acquired %s",
                agent_id, agent_type, role_template or "none", ", ".join(skills) or "nothing",
            )
        return replace(
            unchanged, recommissioned=recorded, role_template=role_template, skills_granted=skills,
        )

    async def _log_commissioning(
        self, agent: Any, *, source: str, role_template: str | None,
        skills: tuple[str, ...], tools: tuple[str, ...], reason: str,
    ) -> None:
        if self._event_log is None:
            return
        try:
            await self._event_log.log(
                category="lifecycle", event=COMMISSIONED_EVENT,
                agent_id=agent.id, agent_type=agent.agent_type, pool=agent.pool,
                data={
                    "source": source, "role_template": role_template,
                    "skills": list(skills), "tools": list(tools),
                    "initiated_by": ENROLLMENT_INITIATED_BY, "reason": reason,
                },
            )
        except Exception:
            logger.warning(
                "BF-906: commissioning of %s is recorded in ACM but not in the event log",
                agent.id, exc_info=True,
            )
