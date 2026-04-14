"""AD-428: Agent Skill Framework — developmental competency model.

Data model for skill definitions, proficiency tracking, and agent skill profiles.
Foundation layer — no LLM calls, no I/O in data classes.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite

from probos.protocols import ConnectionFactory, DatabaseConnection
from probos.tools.protocol import ToolPreference

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


from enum import Enum as _Enum


class SkillCategory(_Enum):
    """Three-category skill taxonomy."""
    PCC = "pcc"             # Professional Core Competency — universal crew skills
    ROLE = "role"           # Role/designation skills — department-specific
    ACQUIRED = "acquired"   # Self-developed through experience or mentoring


class ProficiencyLevel(int, _Enum):
    """Seven-level proficiency scale (Dreyfus + Bloom + SFIA unified)."""
    FOLLOW = 1    # Novice: follows explicit procedures
    ASSIST = 2    # Adv. Beginner: recognizes patterns, needs supervision
    APPLY = 3     # Competent: executes independently
    ENABLE = 4    # Competent+: analyzes, decomposes, exercises judgment
    ADVISE = 5    # Proficient: holistic awareness, mentors others
    LEAD = 6      # Expert: innovates, designs new approaches
    SHAPE = 7     # Expert+: sets direction for the domain


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SkillDefinition:
    """A skill that agents can acquire and develop."""
    skill_id: str               # e.g., "threat_analysis", "ward_room_communication"
    name: str                   # Human-readable display name
    category: SkillCategory
    description: str = ""
    domain: str = "*"           # "security", "engineering", "*" (universal)
    prerequisites: list[str] = field(default_factory=list)  # skill_ids required at APPLY+
    decay_rate_days: int = 14   # Days idle before proficiency drops one level
    origin: str = "built_in"    # "built_in" (PCC), "role", "acquired", "designed"
    preferred_tools: list[ToolPreference] = field(default_factory=list)


@dataclass
class AgentSkillRecord:
    """An agent's proficiency in a specific skill."""
    agent_id: str
    skill_id: str
    proficiency: ProficiencyLevel = ProficiencyLevel.FOLLOW
    acquired_at: float = 0.0
    last_exercised: float = 0.0
    exercise_count: int = 0
    acquisition_source: str = "commissioning"  # "commissioning", "qualification", "experience", "mentoring"
    suspended: bool = False     # True if model lacks required capabilities
    assessment_history: list[dict] = field(default_factory=list)
        # [{timestamp, level, source, notes}]

    def to_dict(self) -> dict[str, Any]:
        """Serialize for API/persistence."""
        return {
            "agent_id": self.agent_id,
            "skill_id": self.skill_id,
            "proficiency": self.proficiency.value,
            "proficiency_label": self.proficiency.name.lower(),
            "acquired_at": self.acquired_at,
            "last_exercised": self.last_exercised,
            "exercise_count": self.exercise_count,
            "acquisition_source": self.acquisition_source,
            "suspended": self.suspended,
        }


@dataclass
class SkillProfile:
    """Complete skill profile for an agent."""
    agent_id: str
    pccs: list[AgentSkillRecord] = field(default_factory=list)
    role_skills: list[AgentSkillRecord] = field(default_factory=list)
    acquired_skills: list[AgentSkillRecord] = field(default_factory=list)

    @property
    def all_skills(self) -> list[AgentSkillRecord]:
        return self.pccs + self.role_skills + self.acquired_skills

    @property
    def depth(self) -> int:
        """Max proficiency across all skills."""
        if not self.all_skills:
            return 0
        return max(s.proficiency.value for s in self.all_skills)

    @property
    def breadth(self) -> int:
        """Number of distinct domains with ASSIST+ proficiency."""
        domains = set()
        for s in self.all_skills:
            if s.proficiency.value >= ProficiencyLevel.ASSIST.value and not s.suspended:
                domains.add(s.skill_id)
        return len(domains)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "pccs": [s.to_dict() for s in self.pccs],
            "role_skills": [s.to_dict() for s in self.role_skills],
            "acquired_skills": [s.to_dict() for s in self.acquired_skills],
            "depth": self.depth,
            "breadth": self.breadth,
        }


@dataclass
class QualificationRecord:
    """Tracks an agent's progress through a qualification path (AD-429b)."""
    agent_id: str
    path_id: str  # e.g., "ensign_to_lieutenant"
    started_at: float
    completed_at: float | None = None
    requirement_status: dict[str, bool] = field(default_factory=dict)

    def is_complete(self) -> bool:
        return all(self.requirement_status.values()) if self.requirement_status else False

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "path_id": self.path_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "is_complete": self.is_complete(),
            "requirements": self.requirement_status,
        }


# ---------------------------------------------------------------------------
# Built-in skill definitions
# ---------------------------------------------------------------------------

# ── Built-in Professional Core Competencies ────────────────────────
BUILTIN_PCCS: list[SkillDefinition] = [
    SkillDefinition(
        skill_id="communication",
        name="Communication",
        category=SkillCategory.PCC,
        description="Effective Ward Room participation, report structure, endorsement quality.",
        domain="*",
        decay_rate_days=30,
    ),
    SkillDefinition(
        skill_id="chain_of_command",
        name="Chain of Command",
        category=SkillCategory.PCC,
        description="Standing Orders compliance, escalation protocols, rank-appropriate behavior.",
        domain="*",
        decay_rate_days=30,
    ),
    SkillDefinition(
        skill_id="duty_execution",
        name="Duty Execution",
        category=SkillCategory.PCC,
        description="Completing scheduled duties on time, structured reporting, prioritization.",
        domain="*",
        decay_rate_days=30,
    ),
    SkillDefinition(
        skill_id="collaboration",
        name="Collaboration",
        category=SkillCategory.PCC,
        description="Consensus participation, cross-agent coordination, constructive disagreement.",
        domain="*",
        decay_rate_days=30,
    ),
    SkillDefinition(
        skill_id="knowledge_stewardship",
        name="Knowledge Stewardship",
        category=SkillCategory.PCC,
        description="Contributing to shared knowledge, accurate episodic recording.",
        domain="*",
        decay_rate_days=30,
    ),
    SkillDefinition(
        skill_id="self_assessment",
        name="Self-Assessment",
        category=SkillCategory.PCC,
        description="Recognizing own limitations, requesting assistance appropriately.",
        domain="*",
        decay_rate_days=30,
    ),
    SkillDefinition(
        skill_id="ethical_reasoning",
        name="Ethical Reasoning",
        category=SkillCategory.PCC,
        description="Standing Orders internalization, safety awareness, reversibility preference.",
        domain="*",
        decay_rate_days=30,
    ),
]

# ── Role skill templates per department ────────────────────────────
# Keyed by agent_type → list of SkillDefinition
ROLE_SKILL_TEMPLATES: dict[str, list[SkillDefinition]] = {
    "security_officer": [
        SkillDefinition(skill_id="threat_analysis", name="Threat Analysis", category=SkillCategory.ROLE, domain="security", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="vulnerability_assessment", name="Vulnerability Assessment", category=SkillCategory.ROLE, domain="security", prerequisites=["threat_analysis"], decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="audit_procedures", name="Audit Procedures", category=SkillCategory.ROLE, domain="security", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="agentic_security_review", name="Agentic Security Review", category=SkillCategory.ROLE, domain="security", prerequisites=["threat_analysis"], decay_rate_days=14, origin="role"),
    ],
    "engineering_officer": [
        SkillDefinition(skill_id="code_review", name="Code Review", category=SkillCategory.ROLE, domain="engineering", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="architecture_analysis", name="Architecture Analysis", category=SkillCategory.ROLE, domain="engineering", prerequisites=["code_review"], decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="performance_optimization", name="Performance Optimization", category=SkillCategory.ROLE, domain="engineering", prerequisites=["architecture_analysis"], decay_rate_days=14, origin="role"),
    ],
    "operations_officer": [
        SkillDefinition(skill_id="resource_management", name="Resource Management", category=SkillCategory.ROLE, domain="operations", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="scheduling_optimization", name="Scheduling Optimization", category=SkillCategory.ROLE, domain="operations", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="incident_response", name="Incident Response", category=SkillCategory.ROLE, domain="operations", prerequisites=["resource_management"], decay_rate_days=14, origin="role"),
    ],
    "diagnostician": [
        SkillDefinition(skill_id="health_assessment", name="Health Assessment", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="anomaly_detection", name="Anomaly Detection", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="diagnostic_reasoning", name="Diagnostic Reasoning", category=SkillCategory.ROLE, domain="medical", prerequisites=["health_assessment", "anomaly_detection"], decay_rate_days=14, origin="role"),
    ],
    "scout": [
        SkillDefinition(skill_id="codebase_exploration", name="Codebase Exploration", category=SkillCategory.ROLE, domain="science", decay_rate_days=7, origin="role"),
        SkillDefinition(skill_id="information_gathering", name="Information Gathering", category=SkillCategory.ROLE, domain="science", decay_rate_days=7, origin="role"),
        SkillDefinition(skill_id="pattern_identification", name="Pattern Identification", category=SkillCategory.ROLE, domain="science", prerequisites=["codebase_exploration"], decay_rate_days=7, origin="role"),
    ],
    "counselor": [
        SkillDefinition(skill_id="cognitive_health_eval", name="Cognitive Health Evaluation", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="crew_fitness_assessment", name="Crew Fitness Assessment", category=SkillCategory.ROLE, domain="medical", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="conflict_mediation", name="Conflict Mediation", category=SkillCategory.ROLE, domain="medical", prerequisites=["cognitive_health_eval"], decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="graduated_coaching", name="Graduated Coaching", category=SkillCategory.ROLE, domain="medical", prerequisites=["cognitive_health_eval"], decay_rate_days=14, origin="role"),
    ],
    "architect": [
        SkillDefinition(skill_id="design_review", name="Design Review", category=SkillCategory.ROLE, domain="science", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="strategic_planning", name="Strategic Planning", category=SkillCategory.ROLE, domain="science", prerequisites=["design_review"], decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="technology_evaluation", name="Technology Evaluation", category=SkillCategory.ROLE, domain="science", decay_rate_days=14, origin="role"),
    ],
}


# ---------------------------------------------------------------------------
# SQLite schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS skill_definitions (
    skill_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT DEFAULT '',
    domain TEXT DEFAULT '*',
    prerequisites TEXT DEFAULT '[]',
    decay_rate_days INTEGER DEFAULT 14,
    origin TEXT DEFAULT 'built_in'
);

CREATE TABLE IF NOT EXISTS agent_skills (
    agent_id TEXT NOT NULL,
    skill_id TEXT NOT NULL,
    proficiency INTEGER DEFAULT 1,
    acquired_at REAL DEFAULT 0,
    last_exercised REAL DEFAULT 0,
    exercise_count INTEGER DEFAULT 0,
    acquisition_source TEXT DEFAULT 'commissioning',
    suspended INTEGER DEFAULT 0,
    assessment_history TEXT DEFAULT '[]',
    PRIMARY KEY (agent_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_skills_agent ON agent_skills(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_skills_skill ON agent_skills(skill_id);
CREATE INDEX IF NOT EXISTS idx_skill_defs_category ON skill_definitions(category);
CREATE INDEX IF NOT EXISTS idx_skill_defs_domain ON skill_definitions(domain);

CREATE TABLE IF NOT EXISTS qualification_records (
    agent_id TEXT NOT NULL,
    path_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    completed_at REAL,
    requirement_status TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (agent_id, path_id)
);
"""


# ---------------------------------------------------------------------------
# SkillRegistry — master catalog of skill definitions
# ---------------------------------------------------------------------------


class SkillRegistry:
    """Ship's Computer service — manages the master catalog of skill definitions.

    Infrastructure tier (no identity). Provides CRUD for SkillDefinitions
    and prerequisite DAG queries.
    """

    def __init__(self, db_path: str | None = None, connection_factory: ConnectionFactory | None = None):
        self._db_path = db_path
        self._db: DatabaseConnection | None = None
        # In-memory cache for fast lookup
        self._cache: dict[str, SkillDefinition] = {}
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        if self._db_path:
            self._db = await self._connection_factory.connect(self._db_path)
            await self._db.execute("PRAGMA foreign_keys = ON")
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            # AD-423a: Add preferred_tools column if missing (migration)
            try:
                await self._db.execute(
                    "ALTER TABLE skill_definitions ADD COLUMN preferred_tools TEXT DEFAULT '[]'"
                )
                await self._db.commit()
            except Exception:
                pass  # Column already exists
            # Load existing definitions into cache
            async with self._db.execute("SELECT * FROM skill_definitions") as cur:
                async for row in cur:
                    self._cache[row["skill_id"]] = self._row_to_definition(row)

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _row_to_definition(self, row) -> SkillDefinition:
        prefs_raw = json.loads(row["preferred_tools"] if "preferred_tools" in row.keys() else "[]")
        prefs = [ToolPreference(tool_id=p["tool_id"], priority=p.get("priority", 0), context=p.get("context", "")) for p in prefs_raw]
        return SkillDefinition(
            skill_id=row["skill_id"],
            name=row["name"],
            category=SkillCategory(row["category"]),
            description=row["description"] or "",
            domain=row["domain"] or "*",
            prerequisites=json.loads(row["prerequisites"] or "[]"),
            decay_rate_days=row["decay_rate_days"] or 14,
            origin=row["origin"] or "built_in",
            preferred_tools=prefs,
        )

    async def register_skill(self, defn: SkillDefinition) -> SkillDefinition:
        """Register or update a skill definition."""
        self._cache[defn.skill_id] = defn
        if self._db:
            prefs_json = json.dumps([{"tool_id": p.tool_id, "priority": p.priority, "context": p.context} for p in defn.preferred_tools])
            await self._db.execute(
                "INSERT OR REPLACE INTO skill_definitions "
                "(skill_id, name, category, description, domain, prerequisites, decay_rate_days, origin, preferred_tools) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (defn.skill_id, defn.name, defn.category.value, defn.description,
                 defn.domain, json.dumps(defn.prerequisites), defn.decay_rate_days, defn.origin, prefs_json),
            )
            await self._db.commit()
        return defn

    async def register_builtins(self) -> None:
        """Register all built-in PCCs and role skill templates."""
        for pcc in BUILTIN_PCCS:
            await self.register_skill(pcc)
        for role_skills in ROLE_SKILL_TEMPLATES.values():
            for skill in role_skills:
                await self.register_skill(skill)

    def get_skill(self, skill_id: str) -> SkillDefinition | None:
        """Get a skill definition by ID (from cache)."""
        return self._cache.get(skill_id)

    def list_skills(
        self, category: SkillCategory | None = None, domain: str | None = None,
    ) -> list[SkillDefinition]:
        """List skill definitions with optional filters."""
        result = list(self._cache.values())
        if category:
            result = [s for s in result if s.category == category]
        if domain:
            result = [s for s in result if s.domain == domain or s.domain == "*"]
        return sorted(result, key=lambda s: s.skill_id)

    def get_prerequisites(self, skill_id: str) -> list[str]:
        """Get the full prerequisite DAG for a skill (flattened, deduplicated)."""
        visited: set[str] = set()
        result: list[str] = []

        def _walk(sid: str) -> None:
            defn = self._cache.get(sid)
            if not defn:
                return
            for prereq_id in defn.prerequisites:
                if prereq_id not in visited:
                    visited.add(prereq_id)
                    _walk(prereq_id)
                    result.append(prereq_id)

        _walk(skill_id)
        return result


# ---------------------------------------------------------------------------
# AgentSkillService — per-agent skill records
# ---------------------------------------------------------------------------


class AgentSkillService:
    """Ship's Computer service — manages per-agent skill records.

    Infrastructure tier. Tracks acquisition, proficiency, decay, and
    produces SkillProfiles.
    """

    def __init__(self, db_path: str | None = None, registry: SkillRegistry | None = None, connection_factory: ConnectionFactory | None = None):
        self._db_path = db_path
        self._db: DatabaseConnection | None = None
        self._registry = registry
        self._connection_factory = connection_factory
        if self._connection_factory is None:
            from probos.storage.sqlite_factory import default_factory
            self._connection_factory = default_factory

    async def start(self) -> None:
        if self._db_path:
            self._db = await self._connection_factory.connect(self._db_path)
            await self._db.execute("PRAGMA foreign_keys = ON")
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _row_to_record(self, row) -> AgentSkillRecord:
        return AgentSkillRecord(
            agent_id=row["agent_id"],
            skill_id=row["skill_id"],
            proficiency=ProficiencyLevel(row["proficiency"]),
            acquired_at=row["acquired_at"] or 0.0,
            last_exercised=row["last_exercised"] or 0.0,
            exercise_count=row["exercise_count"] or 0,
            acquisition_source=row["acquisition_source"] or "commissioning",
            suspended=bool(row["suspended"]),
            assessment_history=json.loads(row["assessment_history"] or "[]"),
        )

    async def acquire_skill(
        self,
        agent_id: str,
        skill_id: str,
        source: str = "commissioning",
        proficiency: ProficiencyLevel = ProficiencyLevel.FOLLOW,
    ) -> AgentSkillRecord:
        """Give an agent a skill at a starting proficiency level.

        Raises ValueError if prerequisites are not met.
        """
        # Check prerequisites
        if self._registry:
            defn = self._registry.get_skill(skill_id)
            if defn and defn.prerequisites:
                for prereq_id in defn.prerequisites:
                    existing = await self._get_record(agent_id, prereq_id)
                    if not existing or existing.proficiency.value < ProficiencyLevel.APPLY.value:
                        raise ValueError(
                            f"Prerequisite '{prereq_id}' not met for '{skill_id}' "
                            f"(requires APPLY+, agent has "
                            f"{'none' if not existing else existing.proficiency.name})"
                        )

        now = time.time()
        record = AgentSkillRecord(
            agent_id=agent_id,
            skill_id=skill_id,
            proficiency=proficiency,
            acquired_at=now,
            last_exercised=now,
            exercise_count=0,
            acquisition_source=source,
        )
        await self._upsert_record(record)
        return record

    async def commission_agent(self, agent_id: str, agent_type: str) -> SkillProfile:
        """Assign an agent their initial skill complement (PCCs + role skills).

        Called during agent registration/onboarding.
        """
        # All crew get PCCs at FOLLOW
        for pcc in BUILTIN_PCCS:
            try:
                await self.acquire_skill(
                    agent_id, pcc.skill_id, source="commissioning",
                    proficiency=ProficiencyLevel.FOLLOW,
                )
            except ValueError:
                pass  # Already exists or prereq issue — skip

        # Role-specific skills
        role_skills = ROLE_SKILL_TEMPLATES.get(agent_type, [])
        for skill in role_skills:
            try:
                await self.acquire_skill(
                    agent_id, skill.skill_id, source="commissioning",
                    proficiency=ProficiencyLevel.FOLLOW,
                )
            except ValueError:
                pass  # Prerequisite not met at commissioning — expected for chained skills

        return await self.get_profile(agent_id)

    async def update_proficiency(
        self,
        agent_id: str,
        skill_id: str,
        new_level: ProficiencyLevel,
        source: str = "assessment",
        notes: str = "",
    ) -> AgentSkillRecord | None:
        """Update an agent's proficiency level with assessment record."""
        record = await self._get_record(agent_id, skill_id)
        if not record:
            return None
        record.proficiency = new_level
        record.last_exercised = time.time()
        record.assessment_history.append({
            "timestamp": time.time(),
            "level": new_level.value,
            "source": source,
            "notes": notes,
        })
        await self._upsert_record(record)
        return record

    async def record_exercise(self, agent_id: str, skill_id: str) -> AgentSkillRecord | None:
        """Record that an agent exercised a skill (resets decay timer)."""
        record = await self._get_record(agent_id, skill_id)
        if not record:
            return None
        record.last_exercised = time.time()
        record.exercise_count += 1
        await self._upsert_record(record)
        return record

    async def check_decay(self, now: float | None = None) -> list[AgentSkillRecord]:
        """Find all skills that have decayed due to inactivity.

        Returns list of records that were downgraded.
        """
        if now is None:
            now = time.time()
        decayed: list[AgentSkillRecord] = []
        if not self._db:
            return decayed

        async with self._db.execute(
            "SELECT * FROM agent_skills WHERE proficiency > 1 AND suspended = 0"
        ) as cur:
            async for row in cur:
                record = self._row_to_record(row)
                defn = self._registry.get_skill(record.skill_id) if self._registry else None
                decay_days = defn.decay_rate_days if defn else 14
                idle_seconds = now - record.last_exercised
                idle_days = idle_seconds / 86400.0
                if idle_days >= decay_days:
                    # Drop one level per decay period elapsed
                    levels_dropped = int(idle_days / decay_days)
                    new_level = max(1, record.proficiency.value - levels_dropped)
                    if new_level < record.proficiency.value:
                        record.proficiency = ProficiencyLevel(new_level)
                        record.assessment_history.append({
                            "timestamp": now,
                            "level": new_level,
                            "source": "decay",
                            "notes": f"Inactive for {idle_days:.0f} days",
                        })
                        await self._upsert_record(record)
                        decayed.append(record)
        return decayed

    async def get_profile(self, agent_id: str) -> SkillProfile:
        """Build the complete skill profile for an agent."""
        profile = SkillProfile(agent_id=agent_id)
        if not self._db:
            return profile

        async with self._db.execute(
            "SELECT * FROM agent_skills WHERE agent_id = ?", (agent_id,)
        ) as cur:
            async for row in cur:
                record = self._row_to_record(row)
                defn = self._registry.get_skill(record.skill_id) if self._registry else None
                if defn:
                    if defn.category == SkillCategory.PCC:
                        profile.pccs.append(record)
                    elif defn.category == SkillCategory.ROLE:
                        profile.role_skills.append(record)
                    else:
                        profile.acquired_skills.append(record)
                else:
                    profile.acquired_skills.append(record)
        return profile

    async def get_all_records(self, agent_id: str) -> list[AgentSkillRecord]:
        """Get all skill records for an agent."""
        if not self._db:
            return []
        records: list[AgentSkillRecord] = []
        async with self._db.execute(
            "SELECT * FROM agent_skills WHERE agent_id = ?", (agent_id,)
        ) as cur:
            async for row in cur:
                records.append(self._row_to_record(row))
        return records

    async def check_prerequisites(
        self, agent_id: str, skill_id: str,
    ) -> dict[str, Any]:
        """Check if an agent meets prerequisites for a skill.

        Returns {met: bool, missing: list[str]}.
        """
        if not self._registry:
            return {"met": True, "missing": []}
        defn = self._registry.get_skill(skill_id)
        if not defn or not defn.prerequisites:
            return {"met": True, "missing": []}
        missing: list[str] = []
        for prereq_id in defn.prerequisites:
            record = await self._get_record(agent_id, prereq_id)
            if not record or record.proficiency.value < ProficiencyLevel.APPLY.value:
                missing.append(prereq_id)
        return {"met": len(missing) == 0, "missing": missing}

    async def _get_record(self, agent_id: str, skill_id: str) -> AgentSkillRecord | None:
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT * FROM agent_skills WHERE agent_id = ? AND skill_id = ?",
            (agent_id, skill_id),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return self._row_to_record(row)

    async def _upsert_record(self, record: AgentSkillRecord) -> None:
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO agent_skills "
            "(agent_id, skill_id, proficiency, acquired_at, last_exercised, "
            "exercise_count, acquisition_source, suspended, assessment_history) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record.agent_id, record.skill_id, record.proficiency.value,
             record.acquired_at, record.last_exercised, record.exercise_count,
             record.acquisition_source, int(record.suspended),
             json.dumps(record.assessment_history)),
        )
        await self._db.commit()

    # -------------------------------------------------------------------
    # Qualification tracking (AD-429b)
    # -------------------------------------------------------------------

    async def start_qualification(self, agent_id: str, path_id: str) -> QualificationRecord:
        """Start tracking a qualification path for an agent."""
        record = QualificationRecord(
            agent_id=agent_id,
            path_id=path_id,
            started_at=time.time(),
        )
        await self._save_qualification_record(record)
        return record

    async def evaluate_qualification(
        self, agent_id: str, path_id: str, ontology: Any
    ) -> QualificationRecord | None:
        """Evaluate an agent's current qualification status against path requirements."""
        if not ontology:
            return None
        parts = path_id.split("_to_")
        if len(parts) != 2:
            return None
        qual_path = ontology.get_qualification_path(parts[0], parts[1])
        if not qual_path:
            return None

        profile = await self.get_profile(agent_id)

        # Get role template for scope-based checks
        assignment = ontology.get_assignment_for_agent_by_id(agent_id)
        role_template = None
        if assignment:
            role_template = ontology.get_role_template(assignment.post_id)

        status: dict[str, bool] = {}
        for req in qual_path.requirements:
            key = f"{req.type}_{req.scope}"
            if req.scope == "all_pccs":
                pcc_records = profile.pccs
                if pcc_records:
                    status[key] = all(
                        r.proficiency.value >= req.min_proficiency for r in pcc_records
                    )
                else:
                    status[key] = False
            elif req.scope == "role_skills":
                role_records = profile.role_skills
                if req.min_count is not None:
                    count = sum(1 for r in role_records if r.proficiency.value >= req.min_proficiency)
                    status[key] = count >= req.min_count
                else:
                    status[key] = all(
                        r.proficiency.value >= req.min_proficiency for r in role_records
                    )
            elif req.scope == "required_role_skills":
                if role_template:
                    required_ids = {s.skill_id for s in role_template.required_skills}
                    required_records = [r for r in profile.role_skills if r.skill_id in required_ids]
                    status[key] = all(
                        r.proficiency.value >= req.min_proficiency for r in required_records
                    ) if required_records else False
                else:
                    status[key] = False

        # Get or create record
        record = await self.get_qualification_record(agent_id, path_id)
        if not record:
            record = QualificationRecord(
                agent_id=agent_id,
                path_id=path_id,
                started_at=time.time(),
            )
        record.requirement_status = status
        if record.is_complete() and not record.completed_at:
            record.completed_at = time.time()

        await self._save_qualification_record(record)
        return record

    async def get_qualification_record(self, agent_id: str, path_id: str) -> QualificationRecord | None:
        """Get a qualification record."""
        if not self._db:
            return None
        async with self._db.execute(
            "SELECT * FROM qualification_records WHERE agent_id = ? AND path_id = ?",
            (agent_id, path_id),
        ) as cur:
            row = await cur.fetchone()
            if not row:
                return None
            return QualificationRecord(
                agent_id=row["agent_id"],
                path_id=row["path_id"],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
                requirement_status=json.loads(row["requirement_status"] or "{}"),
            )

    async def get_all_qualification_records(self, agent_id: str) -> list[QualificationRecord]:
        """Get all qualification records for an agent."""
        if not self._db:
            return []
        records: list[QualificationRecord] = []
        async with self._db.execute(
            "SELECT * FROM qualification_records WHERE agent_id = ?", (agent_id,)
        ) as cur:
            async for row in cur:
                records.append(QualificationRecord(
                    agent_id=row["agent_id"],
                    path_id=row["path_id"],
                    started_at=row["started_at"],
                    completed_at=row["completed_at"],
                    requirement_status=json.loads(row["requirement_status"] or "{}"),
                ))
        return records

    async def _save_qualification_record(self, record: QualificationRecord) -> None:
        """Persist a qualification record to SQLite."""
        if not self._db:
            return
        await self._db.execute(
            "INSERT OR REPLACE INTO qualification_records "
            "(agent_id, path_id, started_at, completed_at, requirement_status) "
            "VALUES (?, ?, ?, ?, ?)",
            (record.agent_id, record.path_id, record.started_at,
             record.completed_at, json.dumps(record.requirement_status)),
        )
        await self._db.commit()
