"""AD-427: Agent Capital Management (ACM) — Core Framework.

Consolidated agent lifecycle and profile service. ACM wraps existing
subsystems (TrustNetwork, EarnedAgency, CrewProfile, SkillFramework,
DutyScheduleTracker) with lifecycle management and a unified profile
view.  Ship's Computer infrastructure — no identity, no personality.

"ACM is the HR department — it doesn't do the work, it manages the
people who do the work."
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from probos.commissioning import commission_chain
from probos.config import format_trust

from probos.protocols import ConnectionFactory, DatabaseConnection

logger = logging.getLogger(__name__)

# ── Lifecycle state machine ─────────────────────────────────────────

class LifecycleState(str, Enum):
    """Agent lifecycle states — HR status, not operational state."""
    REGISTERED = "registered"
    PROBATIONARY = "probationary"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    DECOMMISSIONED = "decommissioned"


# Legal transitions: set of (from_state, to_state)
_LEGAL_TRANSITIONS: set[tuple[str, str]] = {
    (LifecycleState.REGISTERED.value, LifecycleState.PROBATIONARY.value),
    (LifecycleState.PROBATIONARY.value, LifecycleState.ACTIVE.value),
    (LifecycleState.ACTIVE.value, LifecycleState.SUSPENDED.value),
    (LifecycleState.SUSPENDED.value, LifecycleState.ACTIVE.value),
    (LifecycleState.ACTIVE.value, LifecycleState.DECOMMISSIONED.value),
    (LifecycleState.SUSPENDED.value, LifecycleState.DECOMMISSIONED.value),
    (LifecycleState.PROBATIONARY.value, LifecycleState.DECOMMISSIONED.value),
}


@dataclass
class LifecycleTransition:
    """Record of a lifecycle state change."""
    agent_id: str
    from_state: str
    to_state: str
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
    template_fingerprint: str | None = None  # BF-917: the role template last applied; None before BF-917


# ── SQLite schema ───────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS lifecycle (
    agent_id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'registered',
    state_since REAL NOT NULL,
    onboarded_at REAL,
    decommissioned_at REAL
);

CREATE TABLE IF NOT EXISTS lifecycle_transitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    initiated_by TEXT NOT NULL DEFAULT 'system',
    timestamp REAL NOT NULL
);

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


async def _add_template_fingerprint_column(db: DatabaseConnection) -> None:
    """BF-917: add ``commissioning_records.template_fingerprint`` where it is absent.

    A module function, as ``capability_request._migrate_payload_column`` is, to keep
    the service within its SRP budget. Idempotent. Existing rows read NULL: a
    commissioning recorded before BF-917, which the crew enroller re-commissions once.
    """
    cursor = await db.execute("PRAGMA table_info(commissioning_records)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "template_fingerprint" not in columns:
        await db.execute("ALTER TABLE commissioning_records ADD COLUMN template_fingerprint TEXT")

# ── Service ─────────────────────────────────────────────────────────

class AgentCapitalService:
    """Agent Capital Management — consolidated lifecycle and profile service.

    Infrastructure service (Ship's Computer).  Wraps existing subsystems
    into a unified agent management layer.
    """

    def __init__(self, data_dir: str | Path, connection_factory: ConnectionFactory | None = None) -> None:
        self._data_dir = Path(data_dir)
        self._db: DatabaseConnection | None = None
        self._identity_registry: Any = None  # AD-441
        # BF-906 A3: every write section of acm.db holds this lock from its first
        # statement to its commit or rollback. ACM's writers share one connection,
        # so one SQLite transaction: without it, another writer's commit could make
        # half a section durable, or land a failed section's pending statements.
        self._write_lock = asyncio.Lock()
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    def set_identity_registry(self, registry: Any) -> None:
        """Wire the identity registry for birth certificate access."""
        self._identity_registry = registry

    async def start(self) -> None:
        """Initialize ACM database."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db = await self._connection_factory.connect(str(self._data_dir / "acm.db"))
        await self._db.execute("PRAGMA foreign_keys = ON")
        await self._db.executescript(_SCHEMA)
        await _add_template_fingerprint_column(self._db)
        await self._db.commit()

    async def stop(self) -> None:
        """Close ACM database, after any write section in progress has ended."""
        async with self._write_lock:  # BF-906 A3: close never cuts a write section in two
            if self._db:
                await self._db.close()
                self._db = None

    # ── Lifecycle queries ───────────────────────────────────────────

    async def get_lifecycle_state(self, agent_id: str) -> LifecycleState:
        """Get current lifecycle state for an agent."""
        if not self._db:
            return LifecycleState.REGISTERED
        async with self._db.execute(
            "SELECT state FROM lifecycle WHERE agent_id = ?", (agent_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return LifecycleState(row[0])
        return LifecycleState.REGISTERED

    async def get_transition_history(self, agent_id: str) -> list[LifecycleTransition]:
        """Return all transitions for an agent, ordered chronologically."""
        if not self._db:
            return []
        async with self._db.execute(
            "SELECT agent_id, from_state, to_state, reason, initiated_by, timestamp "
            "FROM lifecycle_transitions WHERE agent_id = ? ORDER BY timestamp ASC",
            (agent_id,),
        ) as cursor:
            rows = await cursor.fetchall()
        return [
            LifecycleTransition(
                agent_id=r[0], from_state=r[1], to_state=r[2],
                reason=r[3], initiated_by=r[4], timestamp=r[5],
            )
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
            "initiated_by, reason, timestamp, template_fingerprint FROM commissioning_records WHERE agent_id = ?",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return CommissioningRecord(
            agent_id=row[0], agent_type=row[1], source=row[2], role_template=row[3],
            skills=tuple(json.loads(row[4] or "[]")), tools=tuple(json.loads(row[5] or "[]")),
            initiated_by=row[6], reason=row[7], timestamp=row[8], template_fingerprint=row[9],
        )

    # ── Lifecycle mutations ─────────────────────────────────────────

    async def transition(
        self, agent_id: str, to_state: LifecycleState,
        reason: str = "", initiated_by: str = "system",
    ) -> LifecycleTransition:
        """Transition an agent to a new lifecycle state.

        Validates transition is legal, records the change, returns the
        transition record.  Raises ValueError for illegal transitions.
        """
        # BF-906 A3: the state read, its legality check and both writes are one
        # section, so no other writer commits half of it and two callers cannot
        # both pass the check against the same old state.
        async with self._write_lock:  # BF-906 A3: the state change and its audit row commit together
            if not self._db:
                raise RuntimeError("ACM not started")

            current = await self.get_lifecycle_state(agent_id)
            pair = (current.value, to_state.value)

            if pair not in _LEGAL_TRANSITIONS:
                raise ValueError(
                    f"Illegal lifecycle transition: {current.value} → {to_state.value} "
                    f"for agent {agent_id}"
                )

            now = time.time()

            # Update lifecycle table
            update_fields = "state = ?, state_since = ?"
            update_vals: list[Any] = [to_state.value, now]

            if to_state == LifecycleState.PROBATIONARY:
                update_fields += ", onboarded_at = ?"
                update_vals.append(now)
            elif to_state == LifecycleState.DECOMMISSIONED:
                update_fields += ", decommissioned_at = ?"
                update_vals.append(now)

            update_vals.append(agent_id)
            try:
                await self._db.execute(
                    f"UPDATE lifecycle SET {update_fields} WHERE agent_id = ?",
                    tuple(update_vals),
                )

                # Insert audit trail
                await self._db.execute(
                    "INSERT INTO lifecycle_transitions "
                    "(agent_id, from_state, to_state, reason, initiated_by, timestamp) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (agent_id, current.value, to_state.value, reason, initiated_by, now),
                )
                await self._db.commit()
            except BaseException:
                await self._db.rollback()  # BF-906 A3: a failed transition leaves nothing pending
                raise

        return LifecycleTransition(
            agent_id=agent_id,
            from_state=current.value,
            to_state=to_state.value,
            reason=reason,
            initiated_by=initiated_by,
            timestamp=now,
        )

    # ── High-level operations ───────────────────────────────────────

    async def onboard(
        self, agent_id: str, agent_type: str, pool: str, department: str,
        initiated_by: str = "system",
        sovereign_id: str = "",  # AD-441: persistent UUID
        reason: str = "",  # BF-906: the enrollment path names itself
    ) -> LifecycleTransition:
        """Onboard an agent — register and set to probationary."""
        # BF-906 A3: released before ``transition``, which takes the lock itself.
        async with self._write_lock:  # BF-906 A3: the lifecycle row and its identity mapping commit together
            if not self._db:
                raise RuntimeError("ACM not started")

            now = time.time()
            try:
                await self._db.execute(
                    "INSERT OR IGNORE INTO lifecycle (agent_id, state, state_since) VALUES (?, ?, ?)",
                    (agent_id, LifecycleState.REGISTERED.value, now),
                )

                # AD-441: Record sovereign identity mapping
                if sovereign_id:
                    await self._db.execute(
                        "INSERT OR IGNORE INTO identity_mapping (slot_id, sovereign_id) VALUES (?, ?)",
                        (agent_id, sovereign_id),
                    )

                await self._db.commit()
            except BaseException:
                await self._db.rollback()  # BF-906 A3: a failed registration leaves nothing pending
                raise

        return await self.transition(
            agent_id, LifecycleState.PROBATIONARY,
            reason=reason or f"Onboarded as {agent_type} in {department}",
            initiated_by=initiated_by,
        )

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
        template_fingerprint: str | None = None,
        recommission: bool = False,
    ) -> bool:
        """BF-906: record an agent's commissioning once; False when one already exists.

        In the same commit it appends a lifecycle-history row whose from_state equals
        its to_state: a record of the commissioning, not a state change
        (``_LEGAL_TRANSITIONS`` is unchanged).

        BF-906 A3: the record and its history row are one section under the write
        lock. No other writer's commit can make the record durable without its row,
        and any failure, cancellation included, rolls both back, so the next call
        records again.

        BF-917: the record keeps ``template_fingerprint``, the digest of the role
        template it was commissioned under. With ``recommission=True`` the existing
        record's ``role_template`` and ``template_fingerprint`` are replaced instead,
        in the same section and commit as a "re-commissioned" history row; False when
        there is no record or it already holds this fingerprint. The record's skills,
        tools, source and timestamp stay those of the first commissioning.
        """
        async with self._write_lock:  # BF-906 A3: the record and its history row commit together
            if not self._db:
                raise RuntimeError("ACM not started")
            now = time.time()
            try:
                if recommission:
                    cursor = await self._db.execute(
                        "UPDATE commissioning_records SET role_template = ?, template_fingerprint = ? "
                        "WHERE agent_id = ? AND template_fingerprint IS NOT ?",
                        (role_template, template_fingerprint, agent_id, template_fingerprint),
                    )
                else:
                    cursor = await self._db.execute(
                        "INSERT OR IGNORE INTO commissioning_records (agent_id, agent_type, source, "
                        "role_template, skills_json, tools_json, initiated_by, reason, timestamp, "
                        "template_fingerprint) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (agent_id, agent_type, source, role_template, json.dumps(list(skills)),
                         json.dumps(list(tools)), initiated_by, reason, now, template_fingerprint),
                    )
                if cursor.rowcount == 0:
                    await self._db.commit()
                    return False
                state = (await self.get_lifecycle_state(agent_id)).value
                action = "re-commissioned" if recommission else "commissioned"
                history_reason = (
                    f"{reason}: {action}, role_template={role_template or 'none'}; "
                    f"skills={','.join(skills) or 'none'}; tools={','.join(tools) or 'none'}"
                )
                history_row = (agent_id, state, state, history_reason, initiated_by, now)
                await self._db.execute(_COMMISSIONING_HISTORY_SQL, history_row)
                await self._db.commit()
            except BaseException:  # BF-906 A3: a cancelled caller's record must not stay pending either
                await self._db.rollback()  # BF-906 A3: a failed record leaves nothing pending
                raise
        return True

    async def decommission(
        self, agent_id: str, reason: str = "Decommissioned by Captain",
        initiated_by: str = "captain",
    ) -> LifecycleTransition:
        """Decommission an agent — set to decommissioned state."""
        return await self.transition(
            agent_id, LifecycleState.DECOMMISSIONED,
            reason=reason, initiated_by=initiated_by,
        )

    async def check_activation(self, agent_id: str, trust_score: float, threshold: float = 0.65) -> bool:
        """Check if a probationary agent should be activated based on trust.

        Returns True if transition occurred (AD-442).
        """
        state = await self.get_lifecycle_state(agent_id)
        if state != LifecycleState.PROBATIONARY:
            return False
        if trust_score >= threshold:
            await self.transition(
                agent_id,
                LifecycleState.ACTIVE,
                reason=f"Trust {trust_score:.2f} >= threshold {threshold:.2f} — probationary period complete",
            )
            return True
        return False

    # ── Consolidated profile ────────────────────────────────────────

    async def get_consolidated_profile(
        self, agent_id: str, runtime: Any,
    ) -> dict[str, Any]:
        """Consolidated profile — single view of an agent across all subsystems."""
        profile: dict[str, Any] = {"agent_id": agent_id}

        # 1. Lifecycle state (this service): an HR status (AD-427). It records the
        #    agent's standing; it does not gate or stop its work (AD-1343).
        state = await self.get_lifecycle_state(agent_id)
        profile["lifecycle_state"] = state.value

        if self._db:
            async with self._db.execute(
                "SELECT state_since, onboarded_at, decommissioned_at "
                "FROM lifecycle WHERE agent_id = ?",
                (agent_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    profile["state_since"] = row[0]
                    profile["onboarded_at"] = row[1]
                    profile["decommissioned_at"] = row[2]

        # 2. Crew profile (AD-376)
        if hasattr(runtime, 'profile_store') and runtime.profile_store:
            crew_profile = runtime.profile_store.get(agent_id)
            if crew_profile:
                profile["callsign"] = crew_profile.callsign
                profile["display_name"] = crew_profile.display_name
                profile["department"] = crew_profile.department
                profile["rank"] = crew_profile.rank.value
                profile["personality"] = {
                    "openness": crew_profile.personality.openness,
                    "conscientiousness": crew_profile.personality.conscientiousness,
                    "extraversion": crew_profile.personality.extraversion,
                    "agreeableness": crew_profile.personality.agreeableness,
                    "neuroticism": crew_profile.personality.neuroticism,
                }

        # 3. Trust (Phase 17)
        if hasattr(runtime, 'trust_network'):
            profile["trust"] = format_trust(runtime.trust_network.get_score(agent_id))

        # 4. Earned Agency (AD-357)
        agent = runtime.registry.get(agent_id) if hasattr(runtime, 'registry') else None
        if agent and hasattr(agent, 'rank'):
            from probos.earned_agency import agency_from_rank
            profile["agency_level"] = agency_from_rank(agent.rank).value

        # 5. Skills (AD-428)
        if hasattr(runtime, 'skill_service') and runtime.skill_service:
            try:
                skill_profile = await runtime.skill_service.get_profile(agent_id)
                profile["skill_count"] = skill_profile.total_skills
                profile["avg_proficiency"] = skill_profile.avg_proficiency
            except Exception:
                logger.debug("Skill profile fetch failed", exc_info=True)

        # 6. Episodic memory count
        if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
            if hasattr(runtime.episodic_memory, 'count_for_agent'):
                try:
                    profile["episode_count"] = await runtime.episodic_memory.count_for_agent(agent_id)
                except Exception:
                    logger.debug("Episode count failed", exc_info=True)

        # 7. Cognitive skills (AD-596) — instruction-knowledge the agent has access to.
        #    AD-885: filtered by the agent's crew identity (department + rank) so the
        #    lens shows what THIS agent can actually see, not the ship-wide catalogue.
        if hasattr(runtime, 'cognitive_skill_catalog') and runtime.cognitive_skill_catalog:
            try:
                descriptions = runtime.cognitive_skill_catalog.get_descriptions(
                    department=profile.get("department"),
                    agent_rank=profile.get("rank"),
                )
                profile["cognitive_skills"] = [
                    {"name": name, "description": description, "skill_id": skill_id}
                    for (name, description, skill_id) in descriptions
                ]
                profile["cognitive_skill_count"] = len(descriptions)
            except Exception:
                logger.debug("Cognitive skill fetch failed", exc_info=True)

        # 8. Tool grants (AD-423) — tools this agent is permitted to invoke. Resolved
        #    through the real permission chain using the agent's true rank/department
        #    (from block 2 crew identity); falling back to ensign-level would understate
        #    a senior agent's grants.
        if hasattr(runtime, 'tool_registry') and runtime.tool_registry:
            try:
                from probos.tools.protocol import ToolPermission

                agent_rank = profile.get("rank") or "ensign"
                agent_department = profile.get("department")
                granted_tools = [
                    reg.tool_id
                    for reg in runtime.tool_registry.list_tools()
                    if runtime.tool_registry.check_permission(
                        agent_id,
                        reg.tool_id,
                        ToolPermission.READ,
                        agent_department=agent_department,
                        agent_rank=agent_rank,
                    )
                ]
                profile["tools"] = granted_tools
                profile["tool_count"] = len(granted_tools)
            except Exception:
                logger.debug("Tool grant fetch failed", exc_info=True)

        # 9. Duties (AD-891) — the configured duty schedule for this agent's type.
        #    Read through the public runtime.duty_schedule_tracker accessor (no
        #    Law-of-Demeter reach into proactive_loop._duty_tracker). Shows the
        #    CONFIGURED duties (stable personnel-record view), not the volatile
        #    "due now" set.
        duty_tracker = getattr(runtime, 'duty_schedule_tracker', None)
        if duty_tracker is not None:
            try:
                agent_obj = runtime.registry.get(agent_id) if hasattr(runtime, 'registry') else None
                agent_type = getattr(agent_obj, 'agent_type', None)
                if agent_type:
                    duties = duty_tracker.list_duties_for_agent(agent_type)
                    profile["duties"] = [
                        {
                            "duty_id": d.duty_id,
                            "description": d.description,
                            "cron": d.cron,
                            "interval_seconds": d.interval_seconds,
                            "priority": d.priority,
                        }
                        for d in duties
                    ]
                    profile["duty_count"] = len(duties)
            except Exception:
                logger.debug("Duty schedule fetch failed", exc_info=True)

        return profile

    async def commission(
        self, agent_id: str, agent_type: str, runtime: Any,
        *, preserve_existing: bool = False, grant_issued_by: str = "captain",
    ) -> dict[str, Any]:
        """AD-889: Walk the capability spine Role → Skills → Tools at commissioning.

        The single front door for the Captain's routes and the BF-906 crew enroller.
        The chain itself is :func:`probos.commissioning.commission_chain`: it composes
        runtime services and holds no ACM state, so BF-906 moved it out of this class
        unchanged.
        """
        return await commission_chain(
            agent_id, agent_type, runtime,
            preserve_existing=preserve_existing, grant_issued_by=grant_issued_by,
        )
