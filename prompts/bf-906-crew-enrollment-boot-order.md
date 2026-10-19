# BF-906: crew enrollment is level-triggered — boot-wired crew are onboarded (AD-427/AD-442) and commissioned (AD-889) through one entry point, with an invariant check at startup and in `probos doctor`

**Drafted by:** `claude-architect` (Claude Code, Opus 5.5), 2026-10-18
**Status:** Ready to build. **Issue:** #1594 (with the Captain-approved 2026-10-19 amendment). **Tier:** HIGH (standing instruction 9). **Base:** `origin/main` `cf08d4c9`.
**Dependencies:** none. AD-1343 (#1595) follows this as its own item.
**Re-verified by the orchestrator, 2026-10-19:** all 30 SEARCH/REPLACE pairs and the 3 new files apply to `origin/main` `a9a01281` (BF-904a merged since the draft; between `cf08d4c9` and `a9a01281` only `DECISIONS.md` and `PROGRESS.md` changed among this contract's files). Live premises re-checked by SQL on copies of `acm.db`, `skills.db`, `tool_permissions.db` and `identity.db` in `%LOCALAPPDATA%\ProbOS\data` (originals unchanged by size, mtime and sha256): 16 `birth_certificates` (born 2026-04-16 to 2026-05-21), 16 `slot_mappings`, 0 `lifecycle` rows, 0 `lifecycle_transitions`, 0 `agent_skills`, 0 `qualification_records`, 53 `skill_definitions`, and 1 `tool_access_grants` row (a Captain grant, `browser` write, 2026-07-28).
**Estimated tests:** about 34 new ones (9 real-boot, 18 unit, 7 doctor/route), plus the consumer suites listed per milestone.
**Numbers:** BF-906 is fixed by the issue. AD ceiling: **AD-1344** (`scripts/ad_ceiling.py`, GitHub titles, all states). No new AD is allocated.

## Problem

| Fact | Evidence (`origin/main`) |
|---|---|
| Onboarding is built with no ACM and no ontology, immediately before the fleet | `runtime.py:2791` `ontology=None`, `:2797` `acm=None`, `:2800` `create_agent_fleet` |
| ACM, the ontology, the skill service and the tool stores arrive in Phase 7 | `runtime.py:3255-3256,3275-3276,3301-3302`; ACM is built at `startup/communication.py:778`; crew birth certificates are issued after ACM at `communication.py:895-923` |
| The onboarding hook is skipped while `_acm` is None | `agent_onboarding.py:506`. ACM reaches onboarding only at `finalize.py:5556`, as the private `_acm` |
| The commissioning hook is skipped while `self.acm` is None | `runtime.py:2608-2616`. It runs only at pool creation |
| Nothing enrolls the boot crew afterwards | Only `acm.onboard(` caller: `agent_onboarding.py:512`. Only `acm.commission(` callers: `runtime.py:2611`, `routers/crew.py:628`, `routers/skills.py:140` |
| The comm-profile cache (AD-625) reads empty profiles | `finalize.py:5540-5549` runs at Phase 8 on uncommissioned crew |
| Re-commissioning would reset proficiency | `acquire_skill` builds a fresh FOLLOW/0-exercise record and calls `_upsert_record` = `INSERT OR REPLACE` (`skill_framework.py:1289-1299,1640-1649`). AD-889's "idempotent" (`acm.py:424-425`) means no duplicate *rows*; it does not mean preserved records |
| `registered → suspended/decommissioned` is illegal and probation never ends | `acm.py:39-47,173-177,263-265`; the routes return 409 at `routers/acm.py:61-62,81-82,101-102` |

## Solution (the design and what it rejects)

**Single entry point.** New module `src/probos/crew_enrollment.py` provides `CrewEnrollmentService.enroll(agent, *, source)`. For a crew agent it does three things, in order:
1. If the ACM state is `registered`, call `acm.onboard(…, initiated_by="system", reason=…BF-906…)`.
2. If there is no commissioning record, call `acm.commission(…, preserve_existing=True, grant_issued_by="system")`.
3. If the resulting profile is non-empty, call `acm.record_commissioning(…)` and write the event-log entry `lifecycle/crew_commissioned`.

**Three ways in, one entry point:**

| Source | Path | Definition |
|---|---|---|
| `birth` | the Phase 7 pass `enroll_wired_crew` | the agent's birth certificate was issued during this boot, or it has none |
| `backfill` | the Phase 7 pass | the certificate predates `runtime._start_time_wall` (all 16 live crew) |
| `join` | `wire_agent` → the enroller, set by the pass | any crew agent wired after the pass: post-boot pools, scale-up, AD-1342's visitor-to-crew path |

**Recording.** Each commissioning writes three things:
- one `commissioning_records` row (additive table in acm.db, `PRIMARY KEY agent_id`);
- in the same commit, one `lifecycle_transitions` row with `from_state == to_state`. This is a history record, not a state change; `_LEGAL_TRANSITIONS` is unchanged;
- one event-log row `category="lifecycle", event="crew_commissioned"` carrying source, role template, skills granted, tools granted, `initiated_by="system"` and a reason naming BF-906.

**Agents wired later keep today's semantics.** Today they are onboarded at wire time and commissioned at `create_pool`; after this change both happen at wire time through the same entry point. Recycles are idempotent and record nothing. Scale-ups of crew pools are now covered, which the old hook missed.

**Rejected alternatives:**

| Option | Reason |
|---|---|
| Public `set_acm` setter on onboarding | It fixes onboarding only. It stays edge-triggered at wire time, so crew wired before the setter runs are still missed until a recycle, and commissioning is untouched |
| Move `init_communication` before Phase 2 | Disfavoured by the issue. Phase 7 depends on Phase 4–6 services, so it is a phase reorder far beyond the fix |
| Run the pass inside `finalize_startup` | It would have to land before `:4090` (proactive loop) and `:5540` (comm cache) inside a 2,000-line late-wiring function. The slot between Phase 7 and Phase 8 in `runtime.start()` is earlier and explicit |
| Reuse the AD-1273 rehydrator (`register_rehydrator("*", …)`) | Rehydrators reapply per-instance *volatile* state after a recycle. Enrollment is durable HR state, and reusing them would hide it under the wrong contract |
| Recognise a commissioning by parsing a `lifecycle_transitions` reason | Brittle string matching. A keyed table gives idempotency by construction and a clean doctor query |

## Section 1 — `src/probos/acm.py`

**1a** imports
```
<<<<<<< SEARCH
import logging
import time
from dataclasses import dataclass
=======
import json
import logging
import time
from dataclasses import dataclass
>>>>>>> REPLACE
```
**1b** record type
```
<<<<<<< SEARCH
    reason: str
    initiated_by: str
    timestamp: float


# ── SQLite schema ───────────────────────────────────────────────────
=======
    reason: str
    initiated_by: str
    timestamp: float


@dataclass(frozen=True)
class CommissioningRecord:
    """BF-906: one agent's recorded AD-889 commissioning (one per agent)."""
    agent_id: str
    agent_type: str
    source: str
    role_template: str | None
    skills: tuple[str, ...]
    tools: tuple[str, ...]
    initiated_by: str
    reason: str
    timestamp: float


# ── SQLite schema ───────────────────────────────────────────────────
>>>>>>> REPLACE
```
**1c** schema (additive)
```
<<<<<<< SEARCH
CREATE TABLE IF NOT EXISTS identity_mapping (
    slot_id TEXT PRIMARY KEY,
    sovereign_id TEXT NOT NULL
);
"""
=======
CREATE TABLE IF NOT EXISTS identity_mapping (
    slot_id TEXT PRIMARY KEY,
    sovereign_id TEXT NOT NULL
);

-- BF-906: one row per commissioned agent. Additive; older code ignores it.
CREATE TABLE IF NOT EXISTS commissioning_records (
    agent_id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL,
    source TEXT NOT NULL,
    role_template TEXT,
    skills_json TEXT NOT NULL DEFAULT '[]',
    tools_json TEXT NOT NULL DEFAULT '[]',
    initiated_by TEXT NOT NULL DEFAULT 'system',
    reason TEXT NOT NULL DEFAULT '',
    timestamp REAL NOT NULL
);
"""

_COMMISSIONING_HISTORY_SQL = (
    "INSERT INTO lifecycle_transitions (agent_id, from_state, to_state, reason, initiated_by, timestamp) "
    "VALUES (?, ?, ?, ?, ?, ?)"
)
>>>>>>> REPLACE
```
**1d** queries
```
<<<<<<< SEARCH
            for r in rows
        ]

    # ── Lifecycle mutations ─────────────────────────────────────────
=======
            for r in rows
        ]

    async def has_lifecycle_record(self, agent_id: str) -> bool:
        """BF-906: True when ACM holds a lifecycle row (a missing row reads as REGISTERED)."""
        if not self._db:
            return False
        async with self._db.execute(
            "SELECT 1 FROM lifecycle WHERE agent_id = ?", (agent_id,)
        ) as cursor:
            return await cursor.fetchone() is not None

    async def get_commissioning_record(self, agent_id: str) -> CommissioningRecord | None:
        """BF-906: the agent's recorded commissioning, or None if it was never commissioned."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT agent_id, agent_type, source, role_template, skills_json, tools_json, "
            "initiated_by, reason, timestamp FROM commissioning_records WHERE agent_id = ?",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return CommissioningRecord(
            agent_id=row[0], agent_type=row[1], source=row[2], role_template=row[3],
            skills=tuple(json.loads(row[4] or "[]")), tools=tuple(json.loads(row[5] or "[]")),
            initiated_by=row[6], reason=row[7], timestamp=row[8],
        )

    # ── Lifecycle mutations ─────────────────────────────────────────
>>>>>>> REPLACE
```
**1e** onboarding reason (the new parameter is appended, so positional callers such as `tests/test_acm.py:445` still work)
```
<<<<<<< SEARCH
        sovereign_id: str = "",  # AD-441: persistent UUID
    ) -> LifecycleTransition:
=======
        sovereign_id: str = "",  # AD-441: persistent UUID
        reason: str = "",  # BF-906: the enrollment path names itself
    ) -> LifecycleTransition:
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
            reason=f"Onboarded as {agent_type} in {department}",
=======
            reason=reason or f"Onboarded as {agent_type} in {department}",
>>>>>>> REPLACE
```
**1f** record
```
<<<<<<< SEARCH
    async def decommission(
        self, agent_id: str, reason: str = "Decommissioned by Captain",
=======
    async def record_commissioning(
        self,
        *,
        agent_id: str,
        agent_type: str,
        source: str,
        role_template: str | None,
        skills: tuple[str, ...],
        tools: tuple[str, ...],
        initiated_by: str = "system",
        reason: str = "",
    ) -> bool:
        """BF-906: record an agent's commissioning once; False when one already exists.

        In the same commit it appends a lifecycle-history row whose from_state equals
        its to_state: a record of the commissioning, not a state change
        (``_LEGAL_TRANSITIONS`` is unchanged).
        """
        if not self._db:
            raise RuntimeError("ACM not started")
        now = time.time()
        cursor = await self._db.execute(
            "INSERT OR IGNORE INTO commissioning_records (agent_id, agent_type, source, "
            "role_template, skills_json, tools_json, initiated_by, reason, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (agent_id, agent_type, source, role_template, json.dumps(list(skills)),
             json.dumps(list(tools)), initiated_by, reason, now),
        )
        if cursor.rowcount == 0:
            await self._db.commit()
            return False
        state = (await self.get_lifecycle_state(agent_id)).value
        history_reason = (
            f"{reason}: commissioned, role_template={role_template or 'none'}; "
            f"skills={','.join(skills) or 'none'}; tools={','.join(tools) or 'none'}"
        )
        history_row = (agent_id, state, state, history_reason, initiated_by, now)
        await self._db.execute(_COMMISSIONING_HISTORY_SQL, history_row)
        await self._db.commit()
        return True

    async def decommission(
        self, agent_id: str, reason: str = "Decommissioned by Captain",
>>>>>>> REPLACE
```
**1g** profile wording
```
<<<<<<< SEARCH
        # 1. Lifecycle state (this service)
=======
        # 1. Lifecycle state (this service): an HR status (AD-427). It records the
        #    agent's standing; it does not gate or stop its work (AD-1343).
>>>>>>> REPLACE
```
**1h** commission: preserve existing records and attribute grants. The defaults keep today's behaviour for `routers/crew.py:628`, `routers/skills.py:140` and `tests/test_ad889_commission_chain.py`.
```
<<<<<<< SEARCH
    async def commission(
        self, agent_id: str, agent_type: str, runtime: Any,
    ) -> dict[str, Any]:
=======
    async def commission(
        self, agent_id: str, agent_type: str, runtime: Any,
        *, preserve_existing: bool = False, grant_issued_by: str = "captain",
    ) -> dict[str, Any]:
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
        # 1. PCCs + legacy role skills (AD-428 commission_agent, unchanged).
        try:
            await skill_service.commission_agent(agent_id, agent_type)
        except Exception:
=======
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
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
            for req in template.required_skills:
                try:
                    level = ProficiencyLevel(req.min_proficiency)
=======
            for req in template.required_skills:
                if req.skill_id in preserved:
                    continue
                try:
                    level = ProficiencyLevel(req.min_proficiency)
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
                            is_restriction=False, reason="commission",
                            issued_by="captain",
=======
                            is_restriction=False, reason="commission",
                            issued_by=grant_issued_by,
>>>>>>> REPLACE
```

## Section 2 — `src/probos/skill_framework.py` (`commission_agent`)
```
<<<<<<< SEARCH
    async def commission_agent(self, agent_id: str, agent_type: str) -> SkillProfile:
        """Assign an agent their initial skill complement (PCCs + role skills).

        Called during agent registration/onboarding.
        """
        # All crew get PCCs at FOLLOW
        for pcc in BUILTIN_PCCS:
            try:
=======
    async def commission_agent(
        self, agent_id: str, agent_type: str, *, skip_skill_ids: frozenset[str] = frozenset(),
    ) -> SkillProfile:
        """Assign an agent their initial skill complement (PCCs + role skills).

        Called during agent registration/onboarding. BF-906: ``skip_skill_ids`` names
        skills the agent already holds; they are not re-acquired, so their
        proficiency, exercise count and history are kept.
        """
        # All crew get PCCs at FOLLOW
        for pcc in BUILTIN_PCCS:
            if pcc.skill_id in skip_skill_ids:
                continue
            try:
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
        role_skills = ROLE_SKILL_TEMPLATES.get(agent_type, [])
        for skill in role_skills:
            try:
=======
        role_skills = ROLE_SKILL_TEMPLATES.get(agent_type, [])
        for skill in role_skills:
            if skill.skill_id in skip_skill_ids:
                continue
            try:
>>>>>>> REPLACE
```

## Section 3 — new `src/probos/crew_enrollment.py` (full file)
```python
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
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from probos.acm import AgentCapitalService, LifecycleState
from probos.crew_utils import is_crew_agent

logger = logging.getLogger(__name__)

SOURCE_BIRTH = "birth"
SOURCE_BACKFILL = "backfill"
SOURCE_JOIN = "join"
ENROLLMENT_SOURCES: frozenset[str] = frozenset({SOURCE_BIRTH, SOURCE_BACKFILL, SOURCE_JOIN})

ENROLLMENT_INITIATED_BY = "system"
ENROLLMENT_REASON = "BF-906 (#1594) crew enrollment"
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

    async def enroll(self, agent: Any, *, source: str) -> CrewEnrollment | None:
        """Onboard and commission ``agent`` if it is crew; None for any other agent."""
        if source not in ENROLLMENT_SOURCES:
            raise ValueError(f"BF-906: unknown enrollment source {source!r}")
        if not is_crew_agent(agent, self._ontology):
            return None
        onboarded = await self._onboard_if_unrecorded(agent, source=source)
        if await self._acm.get_commissioning_record(agent.id) is not None:
            return CrewEnrollment(
                agent_id=agent.id, agent_type=agent.agent_type, source=source,
                onboarded=onboarded, commissioned=False,
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
```

## Section 4 — new `src/probos/startup/crew_enrollment.py` (full file)
```python
"""BF-906 (#1594): the Phase 7 crew enrollment pass and the startup crew invariant check."""

from __future__ import annotations

import logging
from typing import Any

from probos.crew_enrollment import (
    INVARIANT_FAILED_EVENT,
    CrewEnrollmentService,
    CrewInvariantReport,
    check_crew_invariant,
)

logger = logging.getLogger(__name__)


async def enroll_boot_crew(*, runtime: Any, boot_started_at: float) -> CrewEnrollmentService | None:
    """Enroll every agent wired so far, then route every later wiring through the enroller."""
    if runtime.acm is None:
        logger.error(
            "BF-906: ACM is unavailable; no crew member is onboarded or commissioned "
            "this boot, and the crew invariant check reports them",
        )
        return None
    service = CrewEnrollmentService(
        acm=runtime.acm,
        ontology=runtime.ontology,
        skill_service=runtime.skill_service,
        identity_registry=runtime.identity_registry,
        event_log=runtime.event_log,
        commission_context=runtime,
        boot_started_at=boot_started_at,
    )
    try:
        await service.enroll_wired_crew(runtime.registry.all())
    except Exception:
        logger.error("BF-906: the crew enrollment pass failed; the invariant check reports who is missing", exc_info=True)
    runtime.onboarding.set_crew_enroller(service.enroll_joining)
    return service


async def report_crew_invariant(*, runtime: Any) -> CrewInvariantReport | None:
    """Report any crew agent without a lifecycle row or a commissioning, never silently."""
    try:
        report = await check_crew_invariant(
            acm=runtime.acm, skill_service=runtime.skill_service,
            ontology=runtime.ontology, agents=runtime.registry.all(),
        )
    except Exception:
        logger.error("BF-906: the crew invariant could not be evaluated", exc_info=True)
        return None
    if report.ok:
        logger.info("BF-906: crew invariant holds for %d crew agents", report.checked)
        return report
    logger.error(
        "BF-906: crew invariant FAILED (%d crew checked): no ACM lifecycle record: %s; "
        "never commissioned: %s",
        report.checked,
        ", ".join(report.missing_lifecycle) or "none",
        ", ".join(report.never_commissioned) or "none",
    )
    try:
        await runtime.event_log.log(
            category="lifecycle", event=INVARIANT_FAILED_EVENT, data=report.to_dict(),
        )
    except Exception:
        logger.warning("BF-906: the invariant failure could not be written to the event log", exc_info=True)
    return report
```

## Section 5 — `src/probos/agent_onboarding.py`
```
<<<<<<< SEARCH
        self._rehydrators: dict[tuple[str, str], Callable[[Any], Awaitable[None]]] = {}

    def set_birth_chamber(self, chamber: Any) -> None:
=======
        self._rehydrators: dict[tuple[str, str], Callable[[Any], Awaitable[None]]] = {}
        # BF-906: the one crew enrollment entry point; set by the Phase 7 pass.
        self._crew_enroller: Callable[[Any], Awaitable[Any]] | None = None

    def set_crew_enroller(self, enroller: Callable[[Any], Awaitable[Any]] | None) -> None:
        """BF-906: set the crew enrollment entry point (onboard + commission).

        ``startup/crew_enrollment.enroll_boot_crew`` sets it once ACM, the ontology
        and the skill service exist; every agent wired afterwards goes through it.
        The ``acm`` constructor argument is no longer read (kept for its callers).
        """
        self._crew_enroller = enroller

    def set_birth_chamber(self, chamber: Any) -> None:
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
        # AD-427: ACM onboarding for crew agents
        if self._acm and is_crew_agent(agent, self._ontology):
            try:
                state = await self._acm.get_lifecycle_state(agent.id)
                if state.value == "registered":
                    from probos.cognitive.standing_orders import get_department
                    department = (self._ontology.get_agent_department(agent.agent_type) if self._ontology else None) or get_department(agent.agent_type) or "operations"
                    await self._acm.onboard(
                        agent_id=agent.id,
                        agent_type=agent.agent_type,
                        pool=agent.pool,
                        department=department,
                        sovereign_id=getattr(agent, 'sovereign_id', ''),
                    )
            except Exception as e:
                logger.debug("ACM onboard skipped for %s: %s", agent.id, e)
=======
        # AD-427 / AD-889 / BF-906 (#1594): onboarding and commissioning go through
        # the one crew enroller (probos.crew_enrollment). It is unset until Phase 7
        # has ACM and the skill service; crew wired before then are enrolled by that
        # phase's pass, so nothing here depends on when the agent was wired.
        if self._crew_enroller is not None:
            try:
                await self._crew_enroller(agent)
            except Exception:
                logger.error(
                    "BF-906: crew enrollment failed for %s (%s); the crew invariant "
                    "check reports it", agent.id, agent.agent_type, exc_info=True,
                )
>>>>>>> REPLACE
```

## Section 6 — `src/probos/runtime.py`
```
<<<<<<< SEARCH
    from probos.cognitive.intent_grants import IntentGrantStore
=======
    from probos.cognitive.intent_grants import IntentGrantStore
    from probos.crew_enrollment import CrewEnrollmentService
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
    acm: AgentCapitalService | None
    ontology: VesselOntologyService | None
=======
    acm: AgentCapitalService | None
    crew_enrollment: "CrewEnrollmentService | None"  # BF-906
    ontology: VesselOntologyService | None
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
        self.acm: AgentCapitalService | None = None
=======
        self.acm: AgentCapitalService | None = None
        self.crew_enrollment: "CrewEnrollmentService | None" = None  # BF-906: set in start()
>>>>>>> REPLACE
```
Remove the birth hook. The pass and `wire_agent` now own commissioning:
```
<<<<<<< SEARCH
                if on_agent_spawned is not None:
                    await on_agent_spawned(agent)
                # AD-889: commission crew agents at birth — walk Role → Skills → Tools.
                if self.acm and is_crew_agent(agent, self.ontology):
                    try:
                        await self.acm.commission(agent.id, agent.agent_type, self)
                    except Exception:
                        logger.debug(
                            "AD-889: commission skipped for %s (type=%s)",
                            agent.id, getattr(agent, "agent_type", "?"), exc_info=True,
                        )

            await self.event_log.log(
=======
                if on_agent_spawned is not None:
                    await on_agent_spawned(agent)
                # AD-889 commissioning happens in onboarding.wire_agent through the
                # BF-906 crew enroller (or, for the boot crew, in the Phase 7 pass).

            await self.event_log.log(
>>>>>>> REPLACE
```
(`is_crew_agent` stays imported: it is still used at `runtime.py:2238`.)

The pass and the startup check:
```
<<<<<<< SEARCH
        await self._initialize_semantic_work_layer()

        # Phase 8: Finalization (AD-517)
        from probos.startup.finalize import finalize_startup

        fin = await finalize_startup(runtime=self, config=self.config)
        self.conn_manager = fin.conn_manager
        self._night_orders_mgr = fin.night_orders_mgr
        self.watch_manager = fin.watch_manager
        self.proactive_loop = fin.proactive_loop
        self.ward_room_router = fin.ward_room_router
        self.self_mod_manager = fin.self_mod_manager
        self.dream_adapter = fin.dream_adapter
=======
        await self._initialize_semantic_work_layer()

        # BF-906 (#1594): onboard (AD-427/AD-442) and commission (AD-889) every crew
        # member wired so far. They were wired in Phase 2, before ACM, the ontology and
        # the skill service existed; agents wired from here on reach the same entry
        # point through onboarding.wire_agent. Before Phase 8, so the AD-625
        # communication-profile cache and the proactive loop see commissioned crew.
        from probos.startup.crew_enrollment import enroll_boot_crew, report_crew_invariant

        self.crew_enrollment = await enroll_boot_crew(runtime=self, boot_started_at=self._start_time_wall)

        # Phase 8: Finalization (AD-517)
        from probos.startup.finalize import finalize_startup

        fin = await finalize_startup(runtime=self, config=self.config)
        self.conn_manager = fin.conn_manager
        self._night_orders_mgr = fin.night_orders_mgr
        self.watch_manager = fin.watch_manager
        self.proactive_loop = fin.proactive_loop
        self.ward_room_router = fin.ward_room_router
        self.self_mod_manager = fin.self_mod_manager
        self.dream_adapter = fin.dream_adapter

        # BF-906: every crew member must now hold an ACM lifecycle record and a
        # commissioning; a breach is an ERROR naming the agents, never silent.
        await report_crew_invariant(runtime=self)
>>>>>>> REPLACE
```
The import must stay inside `start()`: the tests monkeypatch `probos.startup.crew_enrollment.enroll_boot_crew`.

## Section 7 — `src/probos/startup/finalize.py`
```
<<<<<<< SEARCH
    runtime.onboarding._ward_room = runtime.ward_room
    runtime.onboarding._acm = runtime.acm
    runtime.onboarding._start_time_wall = runtime._start_time_wall
=======
    runtime.onboarding._ward_room = runtime.ward_room
    # BF-906: ACM onboarding no longer rides on a private ``_acm``; the crew
    # enroller set in Phase 7 (startup/crew_enrollment.py) owns it.
    runtime.onboarding._start_time_wall = runtime._start_time_wall
>>>>>>> REPLACE
```

## Section 8 — wording: `src/probos/routers/acm.py`, `src/probos/routers/crew.py`
```
<<<<<<< SEARCH
router = APIRouter(prefix="/api/acm", tags=["acm"])
=======
router = APIRouter(prefix="/api/acm", tags=["acm"])

# BF-906: suspend and reinstate record an HR status (AD-427). They do not stop,
# pause or resume the agent's work; the operational stop is AD-1343 (#1595).
HR_STATUS_NOTE = (
    "Records an HR status only. It does not stop or resume the agent's work "
    "(the operational stop is AD-1343)."
)


def _hr_transition_body(status: str, t: Any) -> dict[str, Any]:
    return {
        "status": status,
        "hr_status_only": True,
        "note": HR_STATUS_NOTE,
        "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        },
    }
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
    """AD-427: Suspend an agent (Captain order)."""
=======
    """AD-427: Record an HR suspension for an agent (Captain order).

    Changes the agent's ACM lifecycle status (an HR record) and nothing else: it
    does not stop, pause or refuse the agent's work (AD-1343). Only an ``active``
    agent can be suspended; any other state answers 409.
    """
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
            reason=reason, initiated_by="captain",
        )
        return {"status": "suspended", "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        }}
=======
            reason=reason, initiated_by="captain",
        )
        return _hr_transition_body("suspended", t)
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
    """AD-427: Reinstate a suspended agent."""
=======
    """AD-427: Reinstate a suspended agent's HR status to active.

    An HR record only: a suspension never stopped the agent's work, so reinstating
    resumes nothing (AD-1343).
    """
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
        return {"status": "active", "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        }}
=======
        return _hr_transition_body("active", t)
>>>>>>> REPLACE
```
`routers/crew.py`:
```
<<<<<<< SEARCH
    ``lifecycle_state`` plus cheap ``skill_count`` / ``tool_count``.
    """
=======
    ``lifecycle_state`` plus cheap ``skill_count`` / ``tool_count``.
    ``lifecycle_state`` is the ACM HR status (AD-427): ``suspended`` there is a
    personnel record, not a sign that the agent has stopped working (AD-1343).
    """
>>>>>>> REPLACE
```
```
<<<<<<< SEARCH
        # lifecycle_state — ACM authoritative (async, per-agent).
=======
        # lifecycle_state — the ACM HR status, authoritative (async, per-agent);
        # not an operational state (BF-906, AD-1343).
>>>>>>> REPLACE
```
The HXI label `Lifecycle` (`ui/src/components/personnel/ServiceRecord.tsx:241`) stays as it is. It implies no stop, and the UI never calls `/api/acm` (grep below).

## Section 9 — doctor: new `src/probos/doctor/checks/crew_enrollment_check.py` and its registration
```python
"""BF-906 (#1594): every crew member has an ACM lifecycle record and a commissioning.

Reads identity.db, acm.db and skills.db read-only (``file:...?mode=ro``), so it is
safe while the vessel runs and never creates or changes a store (precedent:
``maintenance/rebuild_episodic.py``). The crew are the slots holding a birth
certificate, issued here or transferred in. A crew member needs a lifecycle row,
and a commissioning record or at least one skill, unless ACM records it as
decommissioned. Mirrors ``probos.crew_enrollment.check_crew_invariant``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from probos.doctor.protocol import CheckOutcome, CheckResult, DoctorContext
from probos.doctor.registry import register_check

_BUSY_TIMEOUT_S = 2.0
_CREW_SQL = (
    "SELECT s.slot_id FROM slot_mappings s JOIN birth_certificates b ON b.agent_uuid = s.agent_uuid"
)
_FOREIGN_CREW_SQL = (
    "SELECT s.slot_id FROM slot_mappings s "
    "JOIN foreign_birth_certificates f ON f.agent_uuid = s.agent_uuid"
)
_LIFECYCLE_SQL = "SELECT agent_id, state FROM lifecycle"
_COMMISSIONED_SQL = "SELECT agent_id FROM commissioning_records"
_SKILLED_SQL = "SELECT DISTINCT agent_id FROM agent_skills"


class _StoreUnreadable(Exception):
    """A store could not be read (locked by the running vessel, or unreadable)."""


def _rows(path: Path, sql: str) -> list[tuple] | None:
    """Rows of ``sql`` from the store at ``path``; None when the store or table is absent."""
    if not path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=_BUSY_TIMEOUT_S)
    except sqlite3.Error as exc:
        raise _StoreUnreadable(f"{path.name}: {exc}") from exc
    try:
        return conn.execute(sql).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" in str(exc):
            return None
        raise _StoreUnreadable(f"{path.name}: {exc}") from exc
    finally:
        conn.close()


@dataclass(frozen=True)
class _CrewEnrollmentCheck:
    name: str = "crew_enrollment"

    async def run(self, ctx: DoctorContext) -> CheckResult:
        data_dir = ctx.data_dir
        try:
            crew_rows = _rows(data_dir / "identity.db", _CREW_SQL)
            if crew_rows is None:
                return CheckResult(CheckOutcome.OK, "Crew enrollment: no crew yet (identity store not initialized)")
            foreign_rows = _rows(data_dir / "identity.db", _FOREIGN_CREW_SQL) or []
            crew = sorted({r[0] for r in crew_rows} | {r[0] for r in foreign_rows})
            lifecycle = {r[0]: r[1] for r in (_rows(data_dir / "acm.db", _LIFECYCLE_SQL) or [])}
            commissioned = {r[0] for r in (_rows(data_dir / "acm.db", _COMMISSIONED_SQL) or [])}
            skilled = {r[0] for r in (_rows(data_dir / "skills.db", _SKILLED_SQL) or [])}
        except _StoreUnreadable as exc:
            return CheckResult(
                CheckOutcome.WARN, f"Crew enrollment: could not read {exc}",
                "The running vessel may be writing to it; rerun `probos doctor`.",
            )
        if not crew:
            return CheckResult(CheckOutcome.OK, "Crew enrollment: no crew have birth certificates yet")
        missing = [a for a in crew if a not in lifecycle]
        never = [
            a for a in crew
            if lifecycle.get(a) != "decommissioned"
            and a not in commissioned and a not in skilled
        ]
        if not missing and not never:
            return CheckResult(
                CheckOutcome.OK,
                f"Crew enrollment: all {len(crew)} crew have an ACM lifecycle record and a commissioning",
            )
        failing = sorted(set(missing) | set(never))
        return CheckResult(
            CheckOutcome.FAIL,
            f"Crew enrollment: {len(failing)} of {len(crew)} crew fail the BF-906 invariant",
            "No ACM lifecycle record: " + (", ".join(missing) or "none") + "\n"
            "Never commissioned: " + (", ".join(never) or "none") + "\n"
            "Restart ProbOS: the startup enrollment pass records them. If this persists, "
            "search the startup log for 'BF-906'.",
        )


register_check(_CrewEnrollmentCheck())
```
`src/probos/doctor/checks/__init__.py`:
```
<<<<<<< SEARCH
    chroma_check,
    security_check,
=======
    chroma_check,
    crew_enrollment_check,
    security_check,
>>>>>>> REPLACE
```
**Doctor semantics.** It reads files without asking the vessel, so it works whether the vessel is running or not.

| Store state | Result |
|---|---|
| identity.db absent | OK, "no crew yet" |
| acm.db absent | every crew member is missing a lifecycle row → FAIL |
| `commissioning_records` table absent (a pre-BF-906 vessel) | no recorded commissionings; agents with skills still pass |
| skills.db absent | no profiles |
| a store locked past 2 s | WARN, never a false OK |

**Known limit:** it reads the default data dir, not a data dir overridden in config.

## Tests

Real-boot fixture. The repo has no shared "real boot" fixture beyond `tests/fixtures/runtime_factory.py` (`make_runtime`/`started_runtime`, `:95-145`). The smallest real one, as in `tests/test_bf879_designed_agents_start_probationary.py:61-73`, is `ProbOSRuntime(config=cfg, data_dir=tmp_path/"data", llm_client=MockLLMClient()); await rt.start()`, with `cfg = SystemConfig()`, `cfg.onboarding.naming_ceremony = False`, `cfg.proactive_cognitive.enabled = False`, `cfg.qa.enabled = False`. It runs every phase in production order, with no network and no LLM. Crew spawn by default (`UtilityAgentsConfig.enabled = True`, `config_models/crew.py:229`), and the ontology loads from the repo's `config/ontology`. Cost: one full boot per test, 12 boots in total. Measure the first run and report it. Do not opt into `fast_teardown`: the pinned lists live in `runtime_factory.py:58-92`. Crew = `[a for a in rt.registry.all() if is_crew_agent(a, rt.ontology)]`; assert as a premise that it is non-empty.

**`tests/test_bf906_crew_enrollment_boot.py`** (real boot)
- **T-B1 `test_every_boot_wired_crew_member_is_onboarded_and_commissioned`.** For every crew agent:
  - `has_lifecycle_record`, with state `probationary`;
  - `get_commissioning_record`, with `source == "birth"`;
  - a non-empty profile;
  - the history holds one `registered→probationary` row (`initiated_by == "system"`, `"BF-906"` in the reason) and one row with `from_state == to_state` containing `source=birth`;
  - exactly one `query_structured(category="lifecycle", event="crew_commissioned")` row with `data["source"] == "birth"`;
  - a non-empty `rt._comm_profiles[agent_id].all_skills` (AD-625 cache).

  Also: the architect's `communication` is at `ProficiencyLevel.ADVISE`, i.e. the template upgrade still happens. Yeoman's record has `role_template is None`, and a WARNING names it.
- **T-B2 `test_a_vessel_whose_crew_predate_commissioning_is_backfilled`.**
  - Boot 1 runs with `enroll_boot_crew` monkeypatched to a no-op; assert as a premise that there are no lifecycle rows. Set one crew trust record to (20, 2) and note its birth certificate. Stop.
  - Boot 2 runs normally. Every crew source is `backfill`. The onboarding reason contains `BF-906` and `source=backfill`. The trust alpha/beta and the birth certificate are unchanged.
- **T-B3 `test_a_second_boot_duplicates_nothing_and_keeps_proficiency`.**
  - Boot 1, then `skill_service.update_proficiency(architect, "communication", LEAD)`. Snapshot the per-crew `agent_skills` rows, the `lifecycle_transitions` count, the `commissioning_records` count, the active grants and the `crew_commissioned` count. Stop.
  - Boot 2 runs with a counting wrapper on `AgentCapitalService.commission`. Assert zero calls, all counts equal, `communication == LEAD`, and no ERROR record containing `BF-906`.
- **T-B4 `test_recommissioning_after_a_lost_record_keeps_existing_skills`.** Boot 1, then set LEAD. Stop and delete the architect's `commissioning_records` row (sqlite3). On boot 2 the architect is re-recorded with `source=backfill`, `communication == LEAD`, and every other skill row's proficiency and exercise count are unchanged.
- **T-B5 `test_crew_joining_after_startup_go_through_the_same_entry_point`.** `await rt.create_pool("bf906_join", "counselor", target_size=1)`. The joiner is `probationary`, its record has `source == "join"`, and exactly one `crew_commissioned` event exists for it.
- **T-B6 `test_the_invariant_fails_red_when_the_pass_is_removed`.**
  - Monkeypatch `enroll_boot_crew` to a no-op and boot. Assert one ERROR record containing `crew invariant FAILED` and every crew id, plus one `crew_invariant_failed` event-log row listing them.
  - Stop. Run `_CrewEnrollmentCheck().run(ctx)` on the same data dir: the result is FAIL and the remediation lists every crew id. The data dir's (name, size, mtime) set is unchanged by the doctor run.
- **T-B7 `test_after_a_real_boot_the_startup_check_and_doctor_agree_it_holds`.** The INFO `crew invariant holds` is logged; after stop, doctor returns OK.
- **T-B8 `test_suspend_then_reinstate_crosses_route_acm_and_roster`.** Use `AsyncClient(transport=ASGITransport(app=create_app(rt)))` (pattern: `tests/test_ad1196_did_key_binding.py:1936`).
  - On a probationary crew member, `POST …/suspend` answers 409.
  - After `rt.acm.check_activation(X, 0.65, 0.65)`, suspend answers 200 with `hr_status_only is True` and `"AD-1343"` in the note. The roster entry reads `suspended`, and `rt.registry.get(X).is_alive` is still True; mark that assertion "AD-1343 replaces this".
  - Reinstate answers 200 and the roster reads `active`.
- **T-B9 `test_check_activation_moves_a_boot_wired_crew_member_at_the_threshold`.** `check_activation(Y, 0.6499, 0.65)` returns False and Y stays probationary; `(Y, 0.65, 0.65)` returns True and Y is `active`.

**`tests/test_bf906_acm_commissioning.py`** (no boot; real ACM, `AgentSkillService` and `ToolPermissionStore` in `tmp_path`, built as in `test_ad889_commission_chain.py:111-126`; stub ontology, agent, event log and identity registry)
- **U1** `record_commissioning`: the first call returns True; a second returns False; exactly one history row, with from == to; the ACM state is unchanged.
- **U2** `has_lifecycle_record` is False for an unknown agent and True after `onboard`.
- **U3** `onboard(reason=…)` uses that reason; with no reason, the old text is kept.
- **U4** `commission(preserve_existing=True)` keeps a pre-existing LEAD skill and its `exercise_count`, and still acquires a missing template skill at the template's level.
- **U5** default `commission` still re-applies template levels over an existing lower record (the apply-role semantics are pinned unchanged).
- **U6** `grant_issued_by="system"` reaches the grant's `issued_by`; the default stays `"captain"`.
- **U7** `commission_agent(skip_skill_ids=…)` skips a PCC and a role skill and keeps their records.
- **U8** `enroll` on a non-crew agent returns None and writes no row.
- **U9** `enroll(source="other")` raises ValueError.
- **U10** with a commissioning that leaves the profile empty (`commission_agent` patched to a no-op, no template): nothing is recorded, an ERROR is logged, and `check_crew_invariant` lists the agent as `never_commissioned`.
- **U11** `check_crew_invariant`: a skilled agent with no record passes; a decommissioned agent with no record passes; with `acm=None` every crew member is listed in both lists.
- **U12** `_boot_source`: a certificate older than the boot gives `backfill`; a newer one or none gives `birth`.
- **U13** the route bodies: `hr_status_only`, the `HR_STATUS_NOTE` text, and the docstrings contain "does not stop" (suspend) and "resumes nothing" (reinstate).

**`tests/test_bf906_doctor_check.py`**
- **D1** no identity.db → OK, and no file is created.
- **D2** crew present but no acm.db → FAIL listing the ids.
- **D3** a pre-BF-906 acm.db (no `commissioning_records`) plus skills → OK for the skilled agents.
- **D4** acm.db held by `BEGIN EXCLUSIVE`, with `_BUSY_TIMEOUT_S` monkeypatched to 0.1 → WARN.
- **D5** a decommissioned agent with no commissioning → no failure.
- **D6** `crew_enrollment` is registered once, and `extras`→`verifier_independence` adjacency holds.
- **D7** a transferred-in slot (`foreign_birth_certificates`) is counted as crew.

## Milestones (each at most about 150 tool calls; cut points are commit-ready)

| # | Scope | Focused tests | Cut point |
|---|---|---|---|
| M1 (~80) | Sections 1–2; U1–U7, U13 (route bodies may land in M3) | new unit file, `tests/test_acm.py`, `tests/test_ad889_commission_chain.py`, `tests/test_onboarding.py` | ACM/skill API complete, existing behaviour unchanged |
| M2 (~150) | Sections 3–7; U8–U12; T-B1–T-B5, T-B9 | new files plus `tests/test_ad1273_agent_rehydration.py`, `tests/test_bf879_designed_agents_start_probationary.py`, `tests/test_persistent_identity.py`, `tests/test_ad1009_roles.py`, `tests/test_ad423c_onboarding.py`, `tests/test_new_crew_auto_welcome.py`, `tests/test_identity_persistence.py`, `tests/test_ad640_tiered_trust.py`, `tests/test_ad595b_naming_billet.py`, `tests/test_ad490_agent_wiring_security_logs.py`, `tests/test_issue1419_failed_start_rollback.py` | the boot crew are enrolled; joining works |
| M3 (~100) | Sections 8–9; T-B6–T-B8; D1–D7; trackers | plus `tests/test_ad801_doctor.py`, `tests/test_ad484_ux_adoption.py`, `tests/test_ad1328_s2a_startup_and_doctor.py`, `tests/test_ad1327_verifier_independence.py` | code-complete; then one mutation campaign, the Diff Reviewer, and one receipted gate |

## Mutation table (one campaign, on the final tree; record the base tree and each file's sha256)

| # | File | Whole-line anchor → mutant | Killed by |
|---|---|---|---|
| 1 | crew_enrollment.py | `        if await self._acm.get_commissioning_record(agent.id) is not None:` → `        if False:` | T-B3 |
| 2 | crew_enrollment.py | `                preserve_existing=True,` → `…=False,` | T-B4 |
| 3 | acm.py | `                if req.skill_id in preserved:` → `                if False:` | T-B4, U4 |
| 4 | skill_framework.py | `            if pcc.skill_id in skip_skill_ids:` → `            if False:` | T-B4, U7 |
| 5 | skill_framework.py | `            if skill.skill_id in skip_skill_ids:` → `            if False:` | U7 |
| 6 | acm.py | `        if preserve_existing:` → `        if True:` | U5 |
| 7 | agent_onboarding.py | `                await self._crew_enroller(agent)` → `                pass` | T-B5 |
| 8 | startup/crew_enrollment.py | `    runtime.onboarding.set_crew_enroller(service.enroll_joining)` → `    pass` | T-B5 |
| 9 | runtime.py | `        self.crew_enrollment = await enroll_boot_crew(runtime=self, boot_started_at=self._start_time_wall)` → `        self.crew_enrollment = None` | T-B1 |
| 10 | crew_enrollment.py | `        if cert is not None and cert.birth_timestamp < self._boot_started_at:` → `        if False:` | T-B2, U12 |
| 11 | acm.py | `        await self._db.execute(_COMMISSIONING_HISTORY_SQL, history_row)` → `        pass` | U1, T-B1 |
| 12 | acm.py | `        if cursor.rowcount == 0:` → `        if False:` | U1 |
| 13 | crew_enrollment.py | `        if not after:` → `        if False:` | U10 |
| 14 | crew_enrollment.py | `        if not await acm.has_lifecycle_record(agent_id):` → `        if False:` | T-B6 |
| 15 | crew_enrollment.py | `        if await _has_skills(skill_service, agent_id):` → `        if False:` | U11 |
| 16 | crew_enrollment.py | `        elif await acm.get_lifecycle_state(agent_id) is LifecycleState.DECOMMISSIONED:` → `        elif False:` | U11 |
| 17 | crew_enrollment_check.py | `        if not missing and not never:` → `        if True:` | T-B6, D2 |
| 18 | crew_enrollment_check.py | `            if lifecycle.get(a) != "decommissioned"` → `            if True` | D5 |
| 19 | routers/acm.py | `        "hr_status_only": True,` → `…False,` | T-B8, U13 |
| 20 | acm.py | `            reason=reason or f"Onboarded as {agent_type} in {department}",` → `            reason=f"Onboarded as {agent_type} in {department}",` | T-B2, U3 |
| 21 | acm.py | `                            issued_by=grant_issued_by,` → `…="captain",` | U6 |
| 22 | crew_enrollment.py | `        if source not in ENROLLMENT_SOURCES:` → `        if False:` | U9 |
| 23 | crew_enrollment.py | `        if not is_crew_agent(agent, self._ontology):` → `        if False:` | U8 |
| 24 | startup/crew_enrollment.py | `    if report.ok:` → `    if True:` | T-B6 |
| 25 | crew_enrollment.py | `        if await self._acm.get_lifecycle_state(agent.id) is not LifecycleState.REGISTERED:` → `        if False:` | T-B3 (no BF-906 ERROR on boot 2) |

Before running, confirm each anchor is unique in its file with `grep -c`. Any survivor is a test gap: fix the test, not the mutant.

## Diff Reviewer properties to verify
1. Every crew agent in the registry at the end of `start()` has a lifecycle row and is commissioned (a recorded commissioning or a non-empty profile), whatever phase it was wired in.
2. `enroll` is the only code path that calls `acm.onboard` or `acm.commission` for crew at boot or on joining. The Captain's routes (`routers/crew.py:628`, `routers/skills.py:140`) keep their defaults.
3. A second boot writes no new skill, grant, lifecycle, history or commissioning row, and no event, for an already-enrolled agent; no pre-existing skill record's proficiency, exercise count or history changes.
4. Trust, rank, episodic memory and identity are not written by any new code.
5. `_LEGAL_TRANSITIONS`, `LifecycleState` and the existing table schemas are byte-identical; the only schema change is the additive `commissioning_records` table.
6. A failure anywhere in enrollment never aborts `start()` and is never logged below ERROR; the invariant check then names the agent.
7. The doctor check opens every store with `mode=ro`, creates no file, and never reports OK when a store could not be read.
8. Suspend and reinstate change only HR status, and their wording says so; no new operational effect.
9. No private attribute is read or written across a module boundary by new code (the removed `_acm` patch is not replaced by another).
10. The startup order is unchanged except for the one pass between Phase 7 and Phase 8 and the check after Phase 8.

## What This Does NOT Change
- Any operational effect of suspension (AD-1343); new lifecycle states or transitions; the phase order beyond the one pass.
- `check_activation` and its single caller (`proactive.py:1085`). The pass does not activate anyone: AD-442 keeps one owner.
- Apply-role / Captain commission semantics (defaults unchanged; see F-155).
- AD-596c `_skill_bridge` / `_skill_profile` attachment to boot crew (F-154).
- The HXI, `config/system.yaml`, the main checkout `D:\ProbOS`.

## Tracking
- **DECISIONS.md:** add `### BF-906 -- Crew enrollment is level-triggered: one entry point, three sources (2026-10-18, #1594)`. Record the decision: birth-time hooks gated on late services are replaced by a Phase 7 pass plus a wire-time enroller; idempotency comes from the lifecycle state, a keyed `commissioning_records` table, and `preserve_existing`. Include the rejected alternatives and the invariant (startup + doctor).
- **PROGRESS.md:** a bold-led paragraph at the top in the existing style: "**BF-906 (2026-10-18), #1594 -- every crew member is now onboarded and commissioned, whenever it was wired.** …", stating sources, records, the invariant and the live backfill of the 16 crew.
- **AD/BF ledger:** no manual edit. `ad-ledger-snapshot.json` is regenerated separately (`.github/copilot-instructions.md:90`); the commit subject starts `BF-906:`.
- **Roadmap Bug Tracker:** no row. `docs/development/roadmap.md:1139` holds only bugs "filed but deliberately not fixed", and OSS bugs are tracked as issues (`:1133`).
- **#1523, F-154** (P2): AD-596c `_skill_bridge`/`_skill_profile` are never attached to boot-wired crew. `wire_agent` caches them only when the bridge is set (`agent_onboarding.py:233-242`), and the bridge reaches onboarding at `finalize.py:5611-5612`, after Phase 2. Its consumers are `cognitive_agent.py:3961,3983,4255,6200,7354,7367,8069`. Fixing it switches on skill-exercise recording for the whole crew, a live behaviour change, so it needs its own BF. Joiners also cache a pre-commission profile.
- **#1523, F-155** (P3): apply-role re-commission (`routers/crew.py:628`) resets existing proficiency and exercise history through `INSERT OR REPLACE`. AD-889's "idempotent" claim (`acm.py:424-425`) is row-level only. Decide whether role re-apply should preserve or set levels.
- **#1582 joining child (requirement to post):** "An agent from another harness that becomes crew is wired through `AgentOnboardingService.wire_agent` after startup, which reaches `CrewEnrollmentService.enroll(source="join")`, the BF-906 entry point. For the `probos doctor` crew_enrollment check to cover it, it must hold a slot mapping to a birth certificate, local or transferred-in."

## Acceptance Criteria
1. T-B1 to T-B9, U1 to U13 and D1 to D7 pass; the consumer suites listed per milestone pass.
2. The mutation campaign kills all 25 rows.
3. The live checklist below passes at the Captain's next restart.
4. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`. The doctor's stdlib `sqlite3` read-only access is a justified exception to the ConnectionFactory rule (a synchronous CLI read of files, precedent `maintenance/rebuild_episodic.py:86-96`).

## Captain: after the next restart (read-only)
0. **Before** starting the new build, with the vessel stopped, copy `acm.db`, `skills.db` and `tool_permissions.db` from `%LOCALAPPDATA%\ProbOS\data`. This is a required action. It is the rollback: restore the three files and run the old build, which ignores `commissioning_records`.
1. The startup log shows `BF-906: crew enrollment pass: 16 crew, 16 onboarded, 16 commissioned (0 birth, 16 backfill)`, two WARNINGs (`yeoman`, `training_officer`: no role template), and `BF-906: crew invariant holds for 16 crew agents`.
2. `probos doctor` shows `✓ Crew enrollment: all 16 crew have an ACM lifecycle record and a commissioning`.
3. `GET /api/crew/roster`: every crew member has `lifecycle_state` `probationary` (or `active` after its first proactive cycle, if trust ≥ 0.65) and `skill_count > 0`. `tool_count` may stay at 0. That is expected: no live skill declares preferred tools.
4. `GET /api/acm/agents/<id>/lifecycle` shows `registered→probationary` (`system`, reason with `BF-906`, `source=backfill`) and a `probationary→probationary` commissioning row.
5. Read-only SQL: acm.db `SELECT source, COUNT(*) FROM commissioning_records GROUP BY source` → `backfill|16`; `SELECT COUNT(*) FROM lifecycle` → 16; skills.db `SELECT COUNT(DISTINCT agent_id) FROM agent_skills` → 16.
6. Restart once more: the pass logs `0 onboarded, 0 commissioned` and every count above is unchanged.
7. Until a crew member is `active`, HR suspend still answers 409 (by design: the legal-transition set is unchanged).

**Targeted rollback (alternative to the file restore):**
- acm.db: `DELETE FROM lifecycle_transitions WHERE initiated_by='system' AND reason LIKE '%BF-906%'`, then `DELETE FROM lifecycle` and `DROP TABLE commissioning_records`. Both lifecycle tables were empty before this change.
- tool_permissions.db: `DELETE FROM tool_access_grants WHERE reason='commission' AND issued_by='system'`.
- skills.db: `DELETE FROM agent_skills WHERE acquisition_source IN ('commissioning','commission')`. There were zero rows before.

## Live premises (re-verified 2026-10-18, read-only)
I could not run SQL: the bridge denies `sqlite3`, Python and `ls`, and Read refuses binary files. Instead I grepped the bytes of the live files with ripgrep, after confirming that none of acm/skills/identity.db has a `-wal` file, so the main files are complete. These are byte-level findings, not query results; item 5 of the checklist above confirms them by SQL.

| Premise | Finding |
|---|---|
| Crew count | **16** crew DIDs with agent_type and callsign in `identity.db`: scout/Wesley, architect/Reed, builder/Anvil, operations_officer/Nova, security_officer/Sentinel, counselor/Ezri, surgeon/Meridian, diagnostician/Chapel, engineering_officer/Forge, data_analyst/Sage, pathologist/Vance, pharmacist/Keiko, training_officer/Tucker, research_specialist/Lyra, systems_analyst/Atlas, yeoman/Yeo. All 16 have birth certificates. They match the 16 assignments at `config/ontology/organization.yaml:379-440` |
| `lifecycle` / `lifecycle_transitions` empty | `probationary\|Onboarded as` occurs 0 times in `acm.db`. Consistent with the issue's query |
| 0 agent skills | `commission` occurs in `skills.db` only as the DDL default `acquisition_source TEXT DEFAULT 'commissioning'`. Consistent with 0 rows. I could not count the 53 definitions; that figure is the Captain's |
| No preferred tools | no `"tool_id": "…"` JSON in `skills.db` |
| No commissioning grants | `commission` occurs 0 times in `tool_permissions.db` and its `-wal` |
| Role templates | 14 of 16 posts have one (`config/ontology/skills.yaml:45-247`). **None** for `yeoman` (post `yeoman`) or `training_officer` (post `chief_training`), and neither is in `ROLE_SKILL_TEMPLATES` (`skill_framework.py:839-907`). Commissioning gives them the PCCs only, records `role_template=None`, and logs a WARNING. That is not an invariant failure |
| Backfill population | all 16. Each gets 1 lifecycle row, 2 history rows, 1 commissioning record, its PCCs plus role skills, and probably 0 grants |
| Not verified | live trust values, i.e. who activates on the first proactive cycle (`trust.db` is WAL and not greppable meaningfully) |

**Open question 5: do the crew lack tools beyond rank-based access?** Commissioning cannot add access, by construction. The AD-888 resolver keeps only tools that already pass `check_permission(agent_id, tool, READ)` with the defaults `agent_rank="ensign"` and `agent_department=None` (`skill_tool_resolver.py:73,87`; `tools/registry.py:322-339`), and grants cannot get past the scope or restriction layers (`registry.py:278-294`). No live skill declares preferred tools. No live `.db` contains `permission_denied` or `ToolPermissionDenied` (byte-level). Emitted `TOOL_PERMISSION_DENIED` events (`events.py:238`) may not be persisted, so this means "none recorded", not "none happened". Whether a role needs a tool beyond rank-based access is a question of role-to-tool policy (ontology tool capabilities, department grants). That is **out of scope** here. Blind spot recorded: commissioning's per-agent READ grants are "grant-up" overrides (`registry.py:315-318`), so they survive a later narrowing of the rank matrix for that agent. That is AD-889's design, applied to 16 agents.

## Prior Art and Blind Spots
This is a bug fix in ProbOS-specific boot plumbing, so external search was skipped, and so was the reference-projects review.
- **Level-triggered reconciliation (the Kubernetes controller pattern, kubernetes.io/docs/concepts/architecture/controller, not fetched).** Absorbed: the defect is an edge-triggered hook that fired before its dependencies existed, and the fix reconciles the desired state at a point where everything exists.
- **AD-1273 (register, then backfill already-wired agents, `finalize.py` + `tests/test_ad1273_agent_rehydration.py:596-601`).** Adapted the shape; rejected the mechanism (see the table above).
- **BF-879, AD-517 PATCH.** The same root cause (services late-bound after Phase 2 wiring).

Blind spots:
- probationary crew cannot be HR-suspended;
- doctor ignores a config-overridden data dir;
- ACM keys by slot id, so a slot reassigned to a transferred-in identity (`identity.py:1555`) inherits that slot's records (pre-existing ACM design);
- the first boot emits about 16×N `SKILL_ACQUIRED` events;
- F-154 and F-155.

## Batching with AD-1343 (#1595)
**Recommendation: no batch; AD-1343 follows as its own item.** The two share no production contract. AD-1343 introduces its own stop owner and seam gates, and its acceptance 5 says "the ACM transition history stays as it is". Its S1 touches the dispatch seams, not the enrollment path. AD-1343's contract needs these from BF-906, all exposed above:
- `AgentCapitalService.has_lifecycle_record` and `get_commissioning_record`;
- `probos.crew_enrollment.check_crew_invariant`, to report crew a vessel-wide stop could not cover;
- `routers/acm.HR_STATUS_NOTE` / `_hr_transition_body`, so its wording updates in one place;
- T-B8's `is_alive` assertion, which AD-1343 must flip deliberately.

It must not reuse ACM `SUSPENDED`, because a probationary agent cannot reach it.

## Decisions
| # | Decision | Envelope |
|---|---|---|
| D1 | Entry point `CrewEnrollmentService.enroll`; Phase 7 pass + `set_crew_enroller`; remove the `create_pool` hook and the `_acm` patch | Architect |
| D2 | Sources birth/backfill/join defined by path and the certificate timestamp | Architect |
| D3 | Idempotency: state, keyed table, `preserve_existing` (the snapshot is taken before step 1) | Architect |
| D4 | Record: additive table + same-state history row + `lifecycle/crew_commissioned` event | Architect (additive schema, not breaking) |
| D5 | Enroller-path grants `issued_by="system"` (audit accuracy; nothing reads `issued_by` for logic); Captain routes keep `"captain"` | Architect (no control weakened) |
| D6 | Invariant: startup ERROR + event; doctor FAIL; neither aborts boot | Architect |
| D7 | Doctor uses stdlib `sqlite3` `mode=ro` (justified exception) | Architect |
| D8 | No activation in the pass; AD-442 stays the single owner | Architect |
| D9 | No-template roles: PCCs only, `role_template=None`, WARNING | Architect |
| D10 | `_skill_profile`/bridge → F-154; apply-role reset → F-155 (fixing them changes live crew behaviour) | Architect |
| D11 | Live backfill: additive and reversible (file restore or targeted SQL); the Captain approved it in the amendment; the Captain's only part is the step-0 copy, which is an action, not a decision | Architect |
| D12 | No roadmap row; the ledger is derived from the commit subject | Architect |
| D13 | AD-1343 is not batched | Architect |

**Nothing here requires a Captain decision.** No control is weakened, no persisted schema or public API breaks (the route bodies gain keys; `status` is kept), and the data operation is reversible.

## Verified Against Codebase (2026-10-18)
For every file cited here, `git diff --stat origin/main -- <file>` is **empty** (run against src/probos/{acm,agent_onboarding,runtime,skill_framework,crew_utils,identity,events,protocols,api,proactive}.py, startup/, routers/{acm,crew,skills}.py, doctor/, tools/, substrate/event_log.py, maintenance/rebuild_episodic.py, cognitive/cognitive_agent.py, config_models/, config/ontology, and the cited tests). The BF-904a files were neither read nor cited. **Re-verify these anchors when main moves:** `runtime.py` 210, 516, 1187, 2603-2617, 3447-3461; `finalize.py` 5551-5557; `agent_onboarding.py` 86-92, 505-520; all of `acm.py` Section 1; `skill_framework.py` 1312-1336; `routers/acm.py`; `routers/crew.py` 52-53, 110; `doctor/checks/__init__.py`.
```
acm.py:39-47 _LEGAL_TRANSITIONS | :82-86 identity_mapping DDL | :126-136 missing row -> REGISTERED
acm.py:218-246 onboard(..., initiated_by="system", sovereign_id="") | :258-273 check_activation
acm.py:413-415 commission(self, agent_id, agent_type, runtime) | :443 commission_agent call
acm.py:455-463 template loop | :516-519 issue_grant(... reason="commission", issued_by="captain")
skill_framework.py:1265-1299 acquire_skill -> _upsert_record | :1312-1336 commission_agent | :1640 INSERT OR REPLACE
skill_framework.py:546-554 ProficiencyLevel | :625-627 all_skills property | :1445-1466 get_profile
agent_onboarding.py:75 self._acm = acm | :88 self._rehydrators | :505-520 ACM block | :233-242 profile cache
runtime.py:149 import is_crew_agent; :2238 second use | :2603-2616 AD-889 hook | :2791,2797 ontology=None, acm=None
runtime.py:3301-3302 self.acm/self.ontology | :3447-3461 semantic layer -> Phase 8 | :1509 _start_time_wall
startup/communication.py:778-780 ACM | :895-923 deferred birth certificates | :926-927 ontology.set_skill_service
startup/finalize.py:5540-5549 comm-profile cache | :5551-5557 late-init patch | :5611-5612 set_skill_bridge | :4090 proactive loop
proactive.py:1079-1087 the only check_activation caller | config_models/experience.py:623 threshold 0.65
ontology/ranks.py:28-33 get_role_template_for_agent | ontology/departments.py:75-82 get_crew_agent_types
tools/skill_tool_resolver.py:73,87 check_permission(agent_id, tool, READ) | tools/registry.py:322-339 defaults ensign/None
identity.py:409-422 birth_certificates | :443-448 slot_mappings | :459 foreign_birth_certificates
substrate/event_log.py:584-596 log(...) | :866-913 query_structured(category, event)
doctor/runner.py:32-39 default data dir | doctor/protocol.py:22-55 | doctor/checks/__init__.py:9-31
tests/test_ad1328_s2a_startup_and_doctor.py:701-705 extras->verifier_independence pin
tests/test_acm.py:440-494 route tests assert result["status"] only
```
**Absence Verified (2026-10-18)**
```
CLAIM: only one acm.onboard caller and three acm.commission callers in src
RUN:   Grep '\.commission\(|\.commission_agent\(|\.onboard\(|check_activation\(' src
FOUND: acm.py:443, agent_onboarding.py:512, runtime.py:2611, proactive.py:1085, routers/crew.py:628, routers/skills.py:140
HOLDS: yes
CLAIM: no test asserts the create_pool commission hook or onboarding._acm
RUN:   Grep 'commission skipped|commission\.assert|onboarding\._acm' tests  -> none
CLAIM: the HXI never calls /api/acm
RUN:   Grep 'api/acm' (repo, excl. node_modules) -> only docs/, prompts/archive/, routers/acm.py:15
CLAIM: transition history has one consumer
RUN:   Grep 'get_transition_history|lifecycle_transitions' src -> acm.py (own) + routers/acm.py:32
CLAIM: nothing reads a tool grant's issued_by for logic
RUN:   Grep 'issued_by ?==|\.issued_by' src -> display/audit only (tools/work_permits.py is a different store)
CLAIM: no doctor check uses sqlite today
RUN:   Grep 'sqlite|mode=ro' src/probos/doctor -> none; precedent maintenance/rebuild_episodic.py:93-94
CLAIM: no test fixes commission_agent's signature
RUN:   Grep 'def commission_agent|commission_agent\s*=' tests -> none
```
