# AD-428: Agent Skill Framework — Developmental Competency Model

## Context

ProbOS agents have **capabilities** (what their LLM can do) and **roles** (what their agent_type says they are), but no formal model of **skills** — measurable, developable competencies that bridge capability and role. The existing `Skill` dataclass in `types.py` (line 406) is a code-execution handle for the self-mod pipeline — `(name, descriptor, source_code, handler)`. It has no concept of proficiency, prerequisites, decay, categories, or developmental tracking.

This AD builds the **foundation data model and services** for ProbOS's skill framework. It does NOT implement skill acquisition through Holodeck, assessment engines, or composite skills — those are future ADs. This is the data layer that everything else builds on.

### Current state

- `types.py` line 406: `Skill` dataclass — intent handler with `origin: str = "designed"`. No proficiency, no category, no decay.
- `earned_agency.py`: `AgencyLevel` enum (REACTIVE/SUGGESTIVE/AUTONOMOUS/UNRESTRICTED), `Rank` enum in `crew_profile.py` (ENSIGN/LIEUTENANT/COMMANDER/SENIOR).
- `crew_profile.py`: `CrewProfile` dataclass with identity, rank, department, personality. No skill tracking.
- `SkillDesigner`/`SkillValidator` in `cognitive/`: Generate and validate skill handler code for utility agents. Utility pipeline, not developmental model.
- No `ModelRegistry` exists yet (Phase 32). Model capabilities cannot be checked programmatically.
- No SQLite persistence for skill definitions or agent skill records.

## Changes

### Step 1: Enums and dataclasses

**File:** `src/probos/skill_framework.py` (NEW FILE)

Create the core data model. Keep everything in one module — this is the foundation, not a sprawling package.

```python
"""AD-428: Agent Skill Framework — developmental competency model.

Data model for skill definitions, proficiency tracking, and agent skill profiles.
Foundation layer — no LLM calls, no I/O in data classes.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SkillCategory(str, Enum):
    """Three-category skill taxonomy."""
    PCC = "pcc"             # Professional Core Competency — universal crew skills
    ROLE = "role"           # Role/designation skills — department-specific
    ACQUIRED = "acquired"   # Self-developed through experience or mentoring


class ProficiencyLevel(int, Enum):
    """Seven-level proficiency scale (Dreyfus + Bloom + SFIA unified)."""
    FOLLOW = 1    # Novice: follows explicit procedures
    ASSIST = 2    # Adv. Beginner: recognizes patterns, needs supervision
    APPLY = 3     # Competent: executes independently
    ENABLE = 4    # Competent+: analyzes, decomposes, exercises judgment
    ADVISE = 5    # Proficient: holistic awareness, mentors others
    LEAD = 6      # Expert: innovates, designs new approaches
    SHAPE = 7     # Expert+: sets direction for the domain


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
                # Need the SkillDefinition to know the domain — return count of unique skill_ids for now
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
```

### Step 2: Built-in PCC and role skill definitions

**File:** `src/probos/skill_framework.py` (same file, after the dataclasses)

Add module-level constants for the 7 PCCs and role skill templates. These are registered at startup.

```python
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
    ],
    "architect": [
        SkillDefinition(skill_id="design_review", name="Design Review", category=SkillCategory.ROLE, domain="science", decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="strategic_planning", name="Strategic Planning", category=SkillCategory.ROLE, domain="science", prerequisites=["design_review"], decay_rate_days=14, origin="role"),
        SkillDefinition(skill_id="technology_evaluation", name="Technology Evaluation", category=SkillCategory.ROLE, domain="science", decay_rate_days=14, origin="role"),
    ],
}
```

### Step 3: SkillRegistry and AgentSkillService

**File:** `src/probos/skill_framework.py` (same file, after the constants)

Two service classes with SQLite persistence. Follow the `PersistentTaskStore` pattern: `__init__(db_path)`, `start()`, `stop()`, aiosqlite with Row factory.

```python
import aiosqlite

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
"""


class SkillRegistry:
    """Ship's Computer service — manages the master catalog of skill definitions.

    Infrastructure tier (no identity). Provides CRUD for SkillDefinitions
    and prerequisite DAG queries.
    """

    def __init__(self, db_path: str | None = None):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        # In-memory cache for fast lookup
        self._cache: dict[str, SkillDefinition] = {}

    async def start(self) -> None:
        if self._db_path:
            self._db = await aiosqlite.connect(self._db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()
            # Load existing definitions into cache
            async with self._db.execute("SELECT * FROM skill_definitions") as cur:
                async for row in cur:
                    self._cache[row["skill_id"]] = self._row_to_definition(row)

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _row_to_definition(self, row) -> SkillDefinition:
        import json
        return SkillDefinition(
            skill_id=row["skill_id"],
            name=row["name"],
            category=SkillCategory(row["category"]),
            description=row["description"] or "",
            domain=row["domain"] or "*",
            prerequisites=json.loads(row["prerequisites"] or "[]"),
            decay_rate_days=row["decay_rate_days"] or 14,
            origin=row["origin"] or "built_in",
        )

    async def register_skill(self, defn: SkillDefinition) -> SkillDefinition:
        """Register or update a skill definition."""
        import json
        self._cache[defn.skill_id] = defn
        if self._db:
            await self._db.execute(
                "INSERT OR REPLACE INTO skill_definitions "
                "(skill_id, name, category, description, domain, prerequisites, decay_rate_days, origin) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (defn.skill_id, defn.name, defn.category.value, defn.description,
                 defn.domain, json.dumps(defn.prerequisites), defn.decay_rate_days, defn.origin),
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
        visited = set()
        result = []

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


class AgentSkillService:
    """Ship's Computer service — manages per-agent skill records.

    Infrastructure tier. Tracks acquisition, proficiency, decay, and
    produces SkillProfiles.
    """

    def __init__(self, db_path: str | None = None, registry: SkillRegistry | None = None):
        self._db_path = db_path
        self._db: aiosqlite.Connection | None = None
        self._registry = registry

    async def start(self) -> None:
        if self._db_path:
            self._db = await aiosqlite.connect(self._db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.executescript(_SCHEMA)
            await self._db.commit()

    async def stop(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _row_to_record(self, row) -> AgentSkillRecord:
        import json
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
        decayed = []
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
        records = []
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
        missing = []
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
        import json
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
```

### Step 4: Runtime integration

**File:** `src/probos/runtime.py`

**4a. Add skill services to Runtime.__init__()** — near the other service initializations (around where `self.ward_room`, `self.persistent_task_store`, etc. are set up). Add:

```python
        # AD-428: Skill Framework
        from probos.skill_framework import SkillRegistry, AgentSkillService
        skills_db = str(self.config.data_dir / "skills.db") if self.config.data_dir else None
        self.skill_registry = SkillRegistry(db_path=skills_db)
        self.skill_service = AgentSkillService(db_path=skills_db, registry=self.skill_registry)
```

**4b. Start/stop skill services** — in `start()` (after other services start), add:

```python
        # AD-428: Skill Framework
        await self.skill_registry.start()
        await self.skill_registry.register_builtins()
        await self.skill_service.start()
```

In `stop()` (before other services stop):

```python
        # AD-428
        await self.skill_service.stop()
        await self.skill_registry.stop()
```

**4c. Wire `build_state_snapshot()`** — in the existing `build_state_snapshot()` method, where per-agent info is assembled (search for `"agency"`), add skill profile summary:

```python
                    # AD-428: Skill profile summary
                    try:
                        profile = await self.skill_service.get_profile(agent.id)
                        agent_info["skill_count"] = len(profile.all_skills)
                        agent_info["skill_depth"] = profile.depth
                        agent_info["skill_breadth"] = profile.breadth
                    except Exception:
                        pass
```

### Step 5: REST API

**File:** `src/probos/api.py`

**5a. GET /api/skills/registry** — list all skill definitions.

```python
    @app.get("/api/skills/registry")
    async def list_skill_definitions(
        category: str | None = None,
        domain: str | None = None,
    ) -> list[dict[str, Any]]:
        """AD-428: List skill definitions from the registry."""
        from probos.skill_framework import SkillCategory
        cat = SkillCategory(category) if category else None
        skills = runtime.skill_registry.list_skills(category=cat, domain=domain)
        return [
            {
                "skill_id": s.skill_id,
                "name": s.name,
                "category": s.category.value,
                "description": s.description,
                "domain": s.domain,
                "prerequisites": s.prerequisites,
                "decay_rate_days": s.decay_rate_days,
                "origin": s.origin,
            }
            for s in skills
        ]
```

**5b. GET /api/skills/agents/{agent_id}/profile** — get an agent's skill profile.

```python
    @app.get("/api/skills/agents/{agent_id}/profile")
    async def get_agent_skill_profile(agent_id: str) -> dict[str, Any]:
        """AD-428: Get an agent's complete skill profile."""
        profile = await runtime.skill_service.get_profile(agent_id)
        return profile.to_dict()
```

**5c. POST /api/skills/agents/{agent_id}/commission** — commission an agent with initial skills.

```python
    @app.post("/api/skills/agents/{agent_id}/commission")
    async def commission_agent_skills(agent_id: str, agent_type: str = "") -> dict[str, Any]:
        """AD-428: Assign initial skill complement (PCCs + role skills)."""
        profile = await runtime.skill_service.commission_agent(agent_id, agent_type)
        return profile.to_dict()
```

**5d. POST /api/skills/agents/{agent_id}/assess** — record a skill assessment.

```python
    class SkillAssessmentRequest(BaseModel):
        skill_id: str
        new_level: int  # ProficiencyLevel value (1-7)
        source: str = "captain"
        notes: str = ""

    @app.post("/api/skills/agents/{agent_id}/assess")
    async def assess_agent_skill(
        agent_id: str, req: SkillAssessmentRequest,
    ) -> dict[str, Any]:
        """AD-428: Record a skill proficiency assessment."""
        from probos.skill_framework import ProficiencyLevel
        try:
            level = ProficiencyLevel(req.new_level)
        except ValueError:
            return JSONResponse(status_code=400, content={"error": f"Invalid proficiency level: {req.new_level}"})
        record = await runtime.skill_service.update_proficiency(
            agent_id, req.skill_id, level, source=req.source, notes=req.notes,
        )
        if not record:
            return JSONResponse(status_code=404, content={"error": "Skill record not found"})
        return record.to_dict()
```

**5e. POST /api/skills/agents/{agent_id}/exercise** — record skill exercise.

```python
    @app.post("/api/skills/agents/{agent_id}/exercise")
    async def record_skill_exercise(agent_id: str, skill_id: str = "") -> dict[str, Any]:
        """AD-428: Record that an agent exercised a skill."""
        record = await runtime.skill_service.record_exercise(agent_id, skill_id)
        if not record:
            return JSONResponse(status_code=404, content={"error": "Skill record not found"})
        return record.to_dict()
```

**5f. GET /api/skills/agents/{agent_id}/prerequisites** — check prerequisites.

```python
    @app.get("/api/skills/agents/{agent_id}/prerequisites/{skill_id}")
    async def check_skill_prerequisites(agent_id: str, skill_id: str) -> dict[str, Any]:
        """AD-428: Check if an agent meets prerequisites for a skill."""
        return await runtime.skill_service.check_prerequisites(agent_id, skill_id)
```

## Tests

**File:** `tests/test_skill_framework.py` (NEW FILE)

All tests use the async pattern from `test_ward_room.py`: `pytest_asyncio.fixture` for setup, `tmp_path` for DB, `start()/stop()` lifecycle.

### Test 1: SkillCategory enum values
```
Assert SkillCategory.PCC.value == "pcc"
Assert SkillCategory.ROLE.value == "role"
Assert SkillCategory.ACQUIRED.value == "acquired"
```

### Test 2: ProficiencyLevel ordering
```
Assert ProficiencyLevel.FOLLOW < ProficiencyLevel.APPLY < ProficiencyLevel.SHAPE
Assert ProficiencyLevel.FOLLOW.value == 1
Assert ProficiencyLevel.SHAPE.value == 7
```

### Test 3: SkillDefinition defaults
```
Create SkillDefinition(skill_id="test", name="Test", category=SkillCategory.PCC).
Assert domain == "*", prerequisites == [], decay_rate_days == 14.
```

### Test 4: AgentSkillRecord.to_dict includes proficiency_label
```
record = AgentSkillRecord(agent_id="worf", skill_id="threat_analysis", proficiency=ProficiencyLevel.APPLY)
d = record.to_dict()
assert d["proficiency"] == 3
assert d["proficiency_label"] == "apply"
```

### Test 5: SkillProfile depth and breadth
```
Create SkillProfile with 3 records at varying proficiency.
Assert depth == max proficiency value.
Assert breadth == count of skills at ASSIST+.
```

### Test 6: SkillProfile.to_dict
```
Create a profile with 1 PCC, 1 role skill.
d = profile.to_dict().
Assert d has "pccs", "role_skills", "acquired_skills", "depth", "breadth".
```

### Test 7: BUILTIN_PCCS has 7 entries
```
from probos.skill_framework import BUILTIN_PCCS
assert len(BUILTIN_PCCS) == 7
assert all(p.category == SkillCategory.PCC for p in BUILTIN_PCCS)
```

### Test 8: ROLE_SKILL_TEMPLATES covers all crew types
```
from probos.skill_framework import ROLE_SKILL_TEMPLATES
assert "security_officer" in ROLE_SKILL_TEMPLATES
assert "engineering_officer" in ROLE_SKILL_TEMPLATES
assert "scout" in ROLE_SKILL_TEMPLATES
assert len(ROLE_SKILL_TEMPLATES) >= 7
```

### Test 9: SkillRegistry register and get
```
Async test. Create SkillRegistry(db_path=tmp), start().
Register a custom SkillDefinition.
get_skill(skill_id) returns it.
list_skills() includes it.
```

### Test 10: SkillRegistry register_builtins
```
Async test. Create SkillRegistry, start, register_builtins().
Assert len(list_skills(category=SkillCategory.PCC)) == 7.
Assert list_skills(category=SkillCategory.ROLE) has entries.
```

### Test 11: SkillRegistry list_skills filters
```
After register_builtins.
list_skills(category=SkillCategory.PCC) returns 7.
list_skills(category=SkillCategory.ROLE, domain="security") returns security skills only.
list_skills(domain="*") returns all universal skills.
```

### Test 12: SkillRegistry get_prerequisites (DAG walk)
```
Register skills: A (no prereqs), B (prereqs=[A]), C (prereqs=[B]).
get_prerequisites("C") returns ["A", "B"].
get_prerequisites("A") returns [].
```

### Test 13: SkillRegistry persists across restart
```
Async test. Register a skill, stop, create new SkillRegistry on same DB, start.
get_skill returns the skill.
```

### Test 14: AgentSkillService acquire_skill
```
Async test. Create AgentSkillService + SkillRegistry, start both, register_builtins.
acquire_skill("worf", "communication", source="commissioning").
Record returned has proficiency == FOLLOW.
get_profile("worf") includes the skill.
```

### Test 15: AgentSkillService commission_agent
```
Async test. commission_agent("worf", "security_officer").
Profile has 7 PCCs + security role skills.
All at FOLLOW proficiency.
```

### Test 16: AgentSkillService prerequisite enforcement
```
Register skill C with prerequisites=["A"]. Agent does NOT have skill A.
acquire_skill("worf", "C") raises ValueError("Prerequisite 'A' not met").
```

### Test 17: AgentSkillService prerequisite enforcement — level check
```
Agent has skill A at FOLLOW (level 1). APPLY (level 3) required.
acquire_skill("worf", "C") raises ValueError (A not at APPLY+).
Update A to APPLY. Now acquire_skill("worf", "C") succeeds.
```

### Test 18: update_proficiency records assessment history
```
commission worf. Update "communication" to APPLY with source="holodeck", notes="passed scenario 3".
Record's proficiency == APPLY.
assessment_history has 1 entry with correct fields.
```

### Test 19: record_exercise updates timestamp and count
```
commission worf. Record initial last_exercised.
record_exercise("worf", "communication").
New last_exercised > old. exercise_count == 1.
```

### Test 20: check_decay drops proficiency after idle period
```
commission worf. Set last_exercised to 15 days ago (for a 14-day decay skill).
check_decay() returns the record. Proficiency dropped by 1 level.
```

### Test 21: check_decay never drops below FOLLOW
```
Set a skill to ASSIST with last_exercised 60 days ago.
check_decay(). Assert proficiency == FOLLOW (not 0 or negative).
```

### Test 22: check_prerequisites returns met/missing
```
Register A, B with prereqs=[A]. Agent has A at APPLY.
check_prerequisites("worf", "B") returns {"met": True, "missing": []}.
Agent without A: check_prerequisites returns {"met": False, "missing": ["A"]}.
```

### Test 23: get_profile categorizes skills correctly
```
commission worf as security_officer.
Profile pccs should have 7 entries.
Profile role_skills should have security skills.
Profile acquired_skills should be empty.
```

### Test 24: AgentSkillRecord persists across restart
```
commission worf, update_proficiency on a skill to APPLY, stop.
Create new service on same DB, start.
get_profile returns worf's skills with APPLY proficiency preserved.
```

### Test 25: SkillProfile.depth with empty profile
```
Empty profile (no skills). depth == 0, breadth == 0.
```

## Constraints

- **Single file** — all enums, dataclasses, constants, and services go in `src/probos/skill_framework.py`. This is a self-contained module. No package directory.
- **No ModelRegistry dependency** — the roadmap mentions model-skill alignment, but `ModelRegistry` doesn't exist yet. `SkillDefinition` does NOT include `capability_requirements` in this AD. That field is added when ModelRegistry arrives (Phase 32). Keep the data model clean — don't add fields that nothing populates.
- **No LLM calls** — this is pure data model, persistence, and service logic. No skill assessment via LLM. No cognitive processing.
- **Shared SQLite DB** — `SkillRegistry` and `AgentSkillService` share the same `skills.db` file and schema. Both connect independently (same pattern as other services).
- **commissioning is idempotent** — calling `commission_agent()` on an already-commissioned agent should `INSERT OR REPLACE`, not fail. Existing records are updated, not duplicated.
- **Prerequisites require APPLY (level 3)** — not just "has the skill." The agent must demonstrate competence before building on it.
- **Decay never drops below FOLLOW (level 1)** — you don't forget a skill exists, but you lose proficiency without practice.
- **`assessment_history` is JSON-serialized** in SQLite — a list of dicts stored as TEXT. Not ideal for querying but matches the existing pattern (CognitiveJournal does the same).
- **Existing `Skill` dataclass in `types.py` is UNCHANGED** — it serves the self-mod pipeline. The new `SkillDefinition`/`AgentSkillRecord` are the developmental model. They coexist. No renaming, no migration. The two concepts may converge later.
- **BUILTIN_PCCS use `origin="built_in"`**. Role skills use `origin="role"`. Acquired skills use `origin="acquired"`. The existing `Skill.origin` values (`"designed"`, `"built_in"`) are unrelated to this taxonomy.

## Run

```bash
cd d:\ProbOS && uv run pytest tests/test_skill_framework.py -x -v 2>&1 | tail -40
```

Broader validation:
```bash
cd d:\ProbOS && uv run pytest tests/test_skill_framework.py tests/test_runtime.py tests/test_api.py -x -v 2>&1 | tail -50
```
