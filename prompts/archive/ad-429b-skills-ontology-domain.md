# AD-429b: Skills Ontology Domain — Formalizing the Competency Model

## Context

AD-429a delivered the Vessel + Organization + Crew ontology domains. `VesselOntologyService` in `src/probos/ontology.py` loads YAML schemas from `config/ontology/`, builds in-memory data models, and provides query methods. Runtime, API, and proactive loop are wired.

AD-428 delivered the Skill Framework (`src/probos/skill_framework.py`, 631 lines): `SkillRegistry`, `AgentSkillService`, `SkillDefinition`, `AgentSkillRecord`, `SkillProfile`, 7 built-in PCCs, role skill templates for 7 agent types, SQLite persistence, REST API at `/api/skills/*`.

**The gap:** The skill framework runs independently. The ontology has no awareness of skills. Two critical concepts exist only in the roadmap — `RoleTemplate` (required skills per post) and `QualificationRecord` (per-agent qualification progress). Without these, promotion is purely trust-based with no formal competency requirement.

AD-429b bridges these by:
1. Adding a `skills.yaml` ontology schema that defines the skill taxonomy and role requirements
2. Adding `RoleTemplate` and `QualificationRecord` data models to the ontology
3. Extending `VesselOntologyService` with skill queries
4. Including skill context in `get_crew_context()` for agent grounding
5. Adding an `/api/ontology/skills/{agent_type}` endpoint

## Important Constraints

- This is AD-429**b** — Skills domain only. Do NOT implement Operations, Communication, Resources, or Records domains.
- The existing `skill_framework.py` is the **source of truth** for skill data (SQLite). The ontology provides a **unified view** — it queries skill_framework, not duplicating storage.
- `RoleTemplate` lives in the ontology (YAML-defined, organization-level). `QualificationRecord` lives in skill_framework (agent-level, SQLite).
- Do NOT modify `skill_framework.py` internals. Only add the `QualificationRecord` model and supporting methods there.
- Keep it lean. The ontology is a queryable data model that composes data from multiple sources.

---

## Step 1: Schema YAML — `config/ontology/skills.yaml`

Create the Skills domain schema file. This defines:
- Skill categories and the proficiency scale (for documentation/grounding)
- Role templates: required and optional skills per post, with minimum proficiency levels

```yaml
# Domain 4: Skills — competency taxonomy and role requirements
#
# Skill definitions and agent skill records live in skill_framework.py (SQLite).
# This schema defines the STRUCTURE and ROLE REQUIREMENTS.
# The ontology service composes both for unified queries.

skill_taxonomy:
  categories:
    - id: pcc
      name: "Proficiency Competency Card"
      description: "Universal competencies all crew must develop"
    - id: role
      name: "Role Skill"
      description: "Competencies specific to a post/department"
    - id: acquired
      name: "Acquired Skill"
      description: "Skills gained through experience or mentoring"

  proficiency_scale:
    - level: 1
      name: "Follow"
      description: "Can follow instructions under supervision"
    - level: 2
      name: "Assist"
      description: "Can assist in performing the skill"
    - level: 3
      name: "Apply"
      description: "Can apply the skill independently"
    - level: 4
      name: "Enable"
      description: "Can enable others to apply the skill"
    - level: 5
      name: "Advise"
      description: "Can advise on complex applications"
    - level: 6
      name: "Lead"
      description: "Can lead skill development and innovation"
    - level: 7
      name: "Shape"
      description: "Can shape the field and define best practices"

# Role templates: what skills each post requires
# Maps post_id (from organization.yaml) to skill requirements
role_templates:
  first_officer:
    required:
      - skill_id: chain_of_command
        min_proficiency: 5  # Advise
      - skill_id: communication
        min_proficiency: 5
      - skill_id: collaboration
        min_proficiency: 4  # Enable
      - skill_id: architecture_review
        min_proficiency: 5
      - skill_id: pattern_recognition
        min_proficiency: 4
    optional:
      - skill_id: ethical_reasoning
        min_proficiency: 3

  counselor:
    required:
      - skill_id: communication
        min_proficiency: 5
      - skill_id: collaboration
        min_proficiency: 5
      - skill_id: self_assessment
        min_proficiency: 4
      - skill_id: wellness_assessment
        min_proficiency: 4
      - skill_id: personality_analysis
        min_proficiency: 4
      - skill_id: crew_counseling
        min_proficiency: 4
    optional:
      - skill_id: ethical_reasoning
        min_proficiency: 4

  chief_engineer:
    required:
      - skill_id: chain_of_command
        min_proficiency: 3
      - skill_id: communication
        min_proficiency: 3
      - skill_id: systems_analysis
        min_proficiency: 5
      - skill_id: performance_optimization
        min_proficiency: 4
      - skill_id: architecture_implementation
        min_proficiency: 4
    optional:
      - skill_id: duty_execution
        min_proficiency: 3

  builder_officer:
    required:
      - skill_id: chain_of_command
        min_proficiency: 2
      - skill_id: duty_execution
        min_proficiency: 3
      - skill_id: systems_analysis
        min_proficiency: 3
      - skill_id: performance_optimization
        min_proficiency: 3
      - skill_id: architecture_implementation
        min_proficiency: 3
    optional:
      - skill_id: collaboration
        min_proficiency: 2

  scout_officer:
    required:
      - skill_id: communication
        min_proficiency: 3
      - skill_id: pattern_recognition
        min_proficiency: 4
      - skill_id: trend_analysis
        min_proficiency: 4
      - skill_id: codebase_exploration
        min_proficiency: 4
    optional:
      - skill_id: knowledge_stewardship
        min_proficiency: 3

  chief_medical:
    required:
      - skill_id: chain_of_command
        min_proficiency: 3
      - skill_id: communication
        min_proficiency: 4
      - skill_id: diagnostic_analysis
        min_proficiency: 5
      - skill_id: health_monitoring
        min_proficiency: 4
      - skill_id: treatment_planning
        min_proficiency: 4
    optional:
      - skill_id: self_assessment
        min_proficiency: 3

  surgeon_officer:
    required:
      - skill_id: duty_execution
        min_proficiency: 3
      - skill_id: diagnostic_analysis
        min_proficiency: 4
      - skill_id: health_monitoring
        min_proficiency: 3
      - skill_id: treatment_planning
        min_proficiency: 4
    optional:
      - skill_id: collaboration
        min_proficiency: 2

  pharmacist_officer:
    required:
      - skill_id: duty_execution
        min_proficiency: 3
      - skill_id: diagnostic_analysis
        min_proficiency: 3
      - skill_id: health_monitoring
        min_proficiency: 3
      - skill_id: treatment_planning
        min_proficiency: 3
    optional:
      - skill_id: knowledge_stewardship
        min_proficiency: 2

  pathologist_officer:
    required:
      - skill_id: duty_execution
        min_proficiency: 3
      - skill_id: diagnostic_analysis
        min_proficiency: 4
      - skill_id: health_monitoring
        min_proficiency: 3
      - skill_id: treatment_planning
        min_proficiency: 3
    optional:
      - skill_id: self_assessment
        min_proficiency: 2

  chief_security:
    required:
      - skill_id: chain_of_command
        min_proficiency: 3
      - skill_id: communication
        min_proficiency: 3
      - skill_id: threat_assessment
        min_proficiency: 5
      - skill_id: access_control
        min_proficiency: 4
      - skill_id: vulnerability_analysis
        min_proficiency: 4
    optional:
      - skill_id: ethical_reasoning
        min_proficiency: 3

  chief_operations:
    required:
      - skill_id: chain_of_command
        min_proficiency: 3
      - skill_id: communication
        min_proficiency: 3
      - skill_id: resource_management
        min_proficiency: 5
      - skill_id: workflow_optimization
        min_proficiency: 4
      - skill_id: system_monitoring
        min_proficiency: 4
    optional:
      - skill_id: duty_execution
        min_proficiency: 3

# Qualification paths: structured requirements for rank transitions
# These define what competencies must be demonstrated for promotion
qualification_paths:
  ensign_to_lieutenant:
    description: "Basic crew qualification — demonstrate fundamental competency"
    requirements:
      - type: pcc_minimum
        description: "All PCCs at ASSIST (level 2) or above"
        min_proficiency: 2
        scope: all_pccs
      - type: role_minimum
        description: "At least 2 role skills at APPLY (level 3)"
        min_proficiency: 3
        min_count: 2
        scope: role_skills

  lieutenant_to_commander:
    description: "Senior crew qualification — demonstrate leadership and depth"
    requirements:
      - type: pcc_minimum
        description: "All PCCs at APPLY (level 3) or above"
        min_proficiency: 3
        scope: all_pccs
      - type: role_minimum
        description: "All required role skills at APPLY (level 3)"
        min_proficiency: 3
        scope: required_role_skills
      - type: role_depth
        description: "At least 1 role skill at ENABLE (level 4)"
        min_proficiency: 4
        min_count: 1
        scope: role_skills

  commander_to_senior:
    description: "Senior officer qualification — demonstrate mastery"
    requirements:
      - type: pcc_minimum
        description: "All PCCs at ENABLE (level 4) or above"
        min_proficiency: 4
        scope: all_pccs
      - type: role_minimum
        description: "All required role skills at ENABLE (level 4)"
        min_proficiency: 4
        scope: required_role_skills
      - type: role_depth
        description: "At least 2 role skills at ADVISE (level 5)"
        min_proficiency: 5
        min_count: 2
        scope: role_skills
```

---

## Step 2: Data Models and Ontology Extension

Extend `src/probos/ontology.py` with Skills domain models and methods.

### New Data Models

Add these to `ontology.py`:

```python
@dataclass
class SkillRequirement:
    """A single skill requirement within a role template."""
    skill_id: str
    min_proficiency: int  # ProficiencyLevel value (1-7)

@dataclass
class RoleTemplate:
    """Required and optional skills for a post. Loaded from skills.yaml."""
    post_id: str
    required_skills: list[SkillRequirement]
    optional_skills: list[SkillRequirement]

@dataclass
class QualificationRequirement:
    """A single requirement within a qualification path."""
    type: str  # "pcc_minimum", "role_minimum", "role_depth"
    description: str
    min_proficiency: int
    scope: str  # "all_pccs", "role_skills", "required_role_skills"
    min_count: int | None = None  # For "role_depth" type

@dataclass
class QualificationPath:
    """Requirements for a rank transition."""
    from_rank: str  # e.g., "ensign"
    to_rank: str    # e.g., "lieutenant"
    description: str
    requirements: list[QualificationRequirement]
```

### VesselOntologyService Extensions

Add to the existing `VesselOntologyService.__init__()`:

```python
self._role_templates: dict[str, RoleTemplate] = {}  # keyed by post_id
self._qualification_paths: dict[str, QualificationPath] = {}  # keyed by "from_to"
```

Add to `initialize()` — load `skills.yaml` after existing YAML loading:

```python
skills_path = self._config_dir / "skills.yaml"
if skills_path.exists():
    self._load_skills_schema(skills_path)
```

### New Loading Method

```python
def _load_skills_schema(self, path: Path) -> None:
    """Load skills.yaml — role templates and qualification paths."""
    import yaml
    with open(path) as f:
        data = yaml.safe_load(f)

    # Parse role templates
    for post_id, template_data in data.get("role_templates", {}).items():
        required = [
            SkillRequirement(s["skill_id"], s["min_proficiency"])
            for s in template_data.get("required", [])
        ]
        optional = [
            SkillRequirement(s["skill_id"], s["min_proficiency"])
            for s in template_data.get("optional", [])
        ]
        self._role_templates[post_id] = RoleTemplate(post_id, required, optional)

    # Parse qualification paths
    for path_key, path_data in data.get("qualification_paths", {}).items():
        parts = path_key.split("_to_")
        if len(parts) != 2:
            continue
        from_rank, to_rank = parts
        reqs = []
        for r in path_data.get("requirements", []):
            reqs.append(QualificationRequirement(
                type=r["type"],
                description=r["description"],
                min_proficiency=r["min_proficiency"],
                scope=r["scope"],
                min_count=r.get("min_count"),
            ))
        self._qualification_paths[path_key] = QualificationPath(
            from_rank=from_rank,
            to_rank=to_rank,
            description=path_data.get("description", ""),
            requirements=reqs,
        )
```

### New Query Methods

```python
# Skills / Role Template queries
def get_role_template(self, post_id: str) -> RoleTemplate | None:
    """Get the skill requirements for a post."""
    return self._role_templates.get(post_id)

def get_role_template_for_agent(self, agent_type: str) -> RoleTemplate | None:
    """Get the role template for an agent's assigned post."""
    assignment = self._assignments.get(agent_type)
    if not assignment:
        return None
    return self._role_templates.get(assignment.post_id)

def get_qualification_path(self, from_rank: str, to_rank: str) -> QualificationPath | None:
    """Get the qualification requirements for a rank transition."""
    key = f"{from_rank}_to_{to_rank}"
    return self._qualification_paths.get(key)

def get_all_qualification_paths(self) -> list[QualificationPath]:
    """Get all defined qualification paths."""
    return list(self._qualification_paths.values())
```

### Extend `get_crew_context()`

Add skill context to the existing `get_crew_context()` method. This requires the runtime to pass an optional `skill_service` reference. Add a `set_skill_service()` method:

```python
def set_skill_service(self, skill_service: Any) -> None:
    """Set reference to AgentSkillService for skill context queries."""
    self._skill_service = skill_service
```

Then in `get_crew_context()`, after the existing context assembly, add:

```python
# Skills context (AD-429b)
role_template = self.get_role_template(assignment.post_id)
if role_template:
    context["role_requirements"] = {
        "required": [
            {"skill": r.skill_id, "min_level": r.min_proficiency}
            for r in role_template.required_skills
        ],
        "optional": [
            {"skill": o.skill_id, "min_level": o.min_proficiency}
            for o in role_template.optional_skills
        ],
    }

# Current skill profile (if skill_service available)
if hasattr(self, '_skill_service') and self._skill_service:
    try:
        # skill_service is async — but get_crew_context is sync,
        # so just include what we can get synchronously.
        # The full profile is available via /api/skills/ endpoints.
        context["skills_note"] = (
            "Your full skill profile is tracked by the Skill Framework. "
            "Role requirements above show what your post demands."
        )
    except Exception:
        pass
```

**Important:** `get_crew_context()` is synchronous but `skill_service.get_profile()` is async. Don't attempt async calls from sync context. Instead, the proactive loop in `_gather_context()` already has async access — it should query skill data separately and merge it. See Step 3.

---

## Step 3: Wire Skill Context into Proactive Loop

In `proactive.py` `_gather_context()`, the ontology context is already injected (AD-429a). Now add skill profile data alongside it:

```python
# Skill profile context (AD-429b)
if hasattr(rt, 'skill_service') and rt.skill_service:
    try:
        profile = await rt.skill_service.get_profile(agent.id)
        if profile:
            skill_summary = []
            for record in profile.all_skills:
                skill_summary.append(f"{record.skill_id}: level {record.proficiency.value} ({record.proficiency.name})")
            if skill_summary:
                context_parts.append(f"Your skill profile: {'; '.join(skill_summary)}")
    except Exception:
        pass
```

This gives agents awareness of their own skill levels during proactive thinks.

---

## Step 4: Wire `set_skill_service()` in Runtime

In `runtime.py`, after both the ontology and skill services are initialized, connect them:

```python
if self.ontology and self.skill_service:
    self.ontology.set_skill_service(self.skill_service)
```

Place this after the skill framework initialization block (around line 1362) and after ontology initialization.

---

## Step 5: QualificationRecord in Skill Framework

Add `QualificationRecord` to `skill_framework.py`. This tracks an agent's progress through a qualification path. It does NOT gate promotion yet (that's a future Earned Agency integration) — it just records progress.

### Data Model

Add to `skill_framework.py`:

```python
@dataclass
class QualificationRecord:
    """Tracks an agent's progress through a qualification path."""
    agent_id: str
    path_id: str  # e.g., "ensign_to_lieutenant"
    started_at: float
    completed_at: float | None = None
    requirement_status: dict[str, bool] = field(default_factory=dict)
    # key = requirement type + scope, value = met or not

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
```

### SQLite Table

Add to the schema creation in `AgentSkillService.start()`:

```sql
CREATE TABLE IF NOT EXISTS qualification_records (
    agent_id TEXT NOT NULL,
    path_id TEXT NOT NULL,
    started_at REAL NOT NULL,
    completed_at REAL,
    requirement_status TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (agent_id, path_id)
);
```

### AgentSkillService Methods

Add to `AgentSkillService`:

```python
async def start_qualification(self, agent_id: str, path_id: str) -> QualificationRecord:
    """Start tracking a qualification path for an agent."""
    record = QualificationRecord(
        agent_id=agent_id,
        path_id=path_id,
        started_at=time.time(),
    )
    # Persist to SQLite
    ...
    return record

async def evaluate_qualification(
    self, agent_id: str, path_id: str, ontology: Any
) -> QualificationRecord | None:
    """Evaluate an agent's current qualification status against path requirements.

    Uses ontology.get_qualification_path() for requirements and
    self.get_profile() for current skill levels.
    """
    if not ontology:
        return None
    qual_path = ontology.get_qualification_path(
        *path_id.split("_to_")
    )
    if not qual_path:
        return None

    profile = await self.get_profile(agent_id)
    if not profile:
        return None

    # Get role template for scope-based checks
    assignment = ontology.get_assignment_for_agent_by_id(agent_id)
    role_template = None
    if assignment:
        role_template = ontology.get_role_template(assignment.post_id)

    status: dict[str, bool] = {}
    for req in qual_path.requirements:
        key = f"{req.type}_{req.scope}"
        if req.scope == "all_pccs":
            # Check all PCC skills meet min_proficiency
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
                # Count how many role skills meet threshold
                count = sum(1 for r in role_records if r.proficiency.value >= req.min_proficiency)
                status[key] = count >= req.min_count
            else:
                status[key] = all(
                    r.proficiency.value >= req.min_proficiency for r in role_records
                )
        elif req.scope == "required_role_skills":
            # Check required role skills from role template
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

    # Persist
    await self._save_qualification_record(record)
    return record

async def get_qualification_record(self, agent_id: str, path_id: str) -> QualificationRecord | None:
    """Get a qualification record."""
    # Query SQLite
    ...

async def get_all_qualification_records(self, agent_id: str) -> list[QualificationRecord]:
    """Get all qualification records for an agent."""
    # Query SQLite
    ...
```

**Important:** The `evaluate_qualification` method needs to look up the agent assignment by agent_id (not agent_type). Add a helper to ontology:

```python
def get_assignment_for_agent_by_id(self, agent_id: str) -> Assignment | None:
    """Find assignment by runtime agent_id (set via wire_agent)."""
    for a in self._assignments.values():
        if a.agent_id == agent_id:
            return a
    return None
```

---

## Step 6: REST API Endpoint

Add to `api.py`:

```python
@app.get("/api/ontology/skills/{agent_type}")
async def get_ontology_skills(agent_type: str):
    """Agent's skill context — role template, current profile, qualification status."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, 503)

    role_template = runtime.ontology.get_role_template_for_agent(agent_type)
    result: dict = {"agent_type": agent_type}

    if role_template:
        result["role_template"] = {
            "post_id": role_template.post_id,
            "required": [
                {"skill_id": r.skill_id, "min_proficiency": r.min_proficiency}
                for r in role_template.required_skills
            ],
            "optional": [
                {"skill_id": o.skill_id, "min_proficiency": o.min_proficiency}
                for o in role_template.optional_skills
            ],
        }
    else:
        result["role_template"] = None

    # Include current skill profile if available
    if runtime.skill_service:
        assignment = runtime.ontology.get_assignment_for_agent(agent_type)
        if assignment and assignment.agent_id:
            profile = await runtime.skill_service.get_profile(assignment.agent_id)
            if profile:
                result["profile"] = profile.to_dict()

    # Include qualification paths
    result["qualification_paths"] = [
        {
            "path_id": f"{qp.from_rank}_to_{qp.to_rank}",
            "description": qp.description,
            "requirements": [
                {"type": r.type, "description": r.description,
                 "min_proficiency": r.min_proficiency, "scope": r.scope,
                 "min_count": r.min_count}
                for r in qp.requirements
            ],
        }
        for qp in runtime.ontology.get_all_qualification_paths()
    ]

    return result
```

---

## Step 7: Tests

Create `tests/test_ontology_skills.py` with:

1. **Skills YAML loading** — Load skills.yaml, verify role templates parsed
2. **Role template query** — `get_role_template("chief_security")` returns Worf's requirements
3. **Role template for agent** — `get_role_template_for_agent("security_officer")` returns same
4. **Unknown post template** — `get_role_template("nonexistent")` returns None
5. **Required skills count** — chief_security has 5 required, 1 optional
6. **Qualification path loading** — 3 paths loaded (ensign→lt, lt→cmdr, cmdr→senior)
7. **Qualification path query** — `get_qualification_path("ensign", "lieutenant")` returns correct requirements
8. **Unknown qualification path** — `get_qualification_path("ensign", "admiral")` returns None
9. **QualificationRecord model** — Create record, verify `is_complete()` logic
10. **QualificationRecord all met** — All requirements True → is_complete() returns True
11. **QualificationRecord partial** — Some False → is_complete() returns False
12. **QualificationRecord to_dict** — Verify serialization
13. **Assignment by agent_id** — `get_assignment_for_agent_by_id()` after `wire_agent()`
14. **Crew context includes role requirements** — `get_crew_context()` now has `role_requirements` key
15. **Skill service wiring** — `set_skill_service()` stores reference

---

## Verification

1. `uv run pytest tests/test_ontology_skills.py -v` — all skills ontology tests pass
2. `uv run pytest tests/test_ontology.py -v` — existing ontology tests still pass (no regression)
3. `uv run pytest` — full suite passes
4. `cd ui && npm run build` — frontend still builds (no TS changes)
5. Manual: `curl http://127.0.0.1:18900/api/ontology/skills/security_officer` returns role template + qualification paths

---

## Files

| File | Action |
|------|--------|
| `config/ontology/skills.yaml` | **NEW** — Skills domain schema with role templates and qualification paths |
| `src/probos/ontology.py` | **MODIFY** — Add SkillRequirement, RoleTemplate, QualificationPath models; load skills.yaml; skill query methods; extend get_crew_context() |
| `src/probos/skill_framework.py` | **MODIFY** — Add QualificationRecord model, SQLite table, evaluate/start/get methods on AgentSkillService |
| `src/probos/runtime.py` | **MODIFY** — Wire ontology.set_skill_service() after both are initialized |
| `src/probos/proactive.py` | **MODIFY** — Add skill profile to _gather_context() |
| `src/probos/api.py` | **MODIFY** — Add /api/ontology/skills/{agent_type} endpoint |
| `tests/test_ontology_skills.py` | **NEW** — 15 tests |
