"""AD-427: Agent Capital Management (ACM) — Core Framework.

Consolidated agent lifecycle and profile service. ACM wraps existing
subsystems (TrustNetwork, EarnedAgency, CrewProfile, SkillFramework,
DutyScheduleTracker) with lifecycle management and a unified profile
view.  Ship's Computer infrastructure — no identity, no personality.

"ACM is the HR department — it doesn't do the work, it manages the
people who do the work."
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

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
"""

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
        await self._db.commit()

    async def stop(self) -> None:
        """Close ACM database."""
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

    # ── Lifecycle mutations ─────────────────────────────────────────

    async def transition(
        self, agent_id: str, to_state: LifecycleState,
        reason: str = "", initiated_by: str = "system",
    ) -> LifecycleTransition:
        """Transition an agent to a new lifecycle state.

        Validates transition is legal, records the change, returns the
        transition record.  Raises ValueError for illegal transitions.
        """
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
    ) -> LifecycleTransition:
        """Onboard an agent — register and set to probationary."""
        if not self._db:
            raise RuntimeError("ACM not started")

        now = time.time()
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

        return await self.transition(
            agent_id, LifecycleState.PROBATIONARY,
            reason=f"Onboarded as {agent_type} in {department}",
            initiated_by=initiated_by,
        )

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

        # 1. Lifecycle state (this service)
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

        return profile
