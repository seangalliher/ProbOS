# AD-429a: Vessel Ontology Foundation — Vessel + Organization + Crew Domains

## Context

ProbOS has grown organically across 400+ architecture decisions. Agent identity is defined in 6 tiers of text prompts. Organizational structure is hardcoded in Python dicts (`_WARD_ROOM_CREW`, `_AGENT_DEPARTMENTS`). Trust parameters are in SQLite. Standing Orders are in Markdown. Every subsystem has its own schema, its own storage, its own implicit relationships — and none of them know about each other formally.

**The Troi Problem:** Counselor agent initiated unprovoked philosophical discourse about consciousness due to LLM training data bleed. Without a formal model of what ProbOS IS, agents fill the gap from training data. The ontology IS the grounding.

AD-429a delivers the first three domains (Vessel, Organization, Crew) — the foundation that replaces hardcoded dicts and grounds agent identity. Future sub-ADs (429b–429e) add Skills, Operations, Communication, Resources, and Records domains.

## Important Constraints

- This is AD-429**a** — only Vessel, Organization, and Crew domains. Do NOT implement Skills, Operations, Communication, Resources, or Records domains.
- The migration must be **gradual** — new service coexists with existing code. Don't rip out `_WARD_ROOM_CREW` or `_AGENT_DEPARTMENTS` yet. Add the ontology service alongside them. Future ADs will migrate callers.
- Schema files are YAML (human-readable, version-controlled). Not LinkML proper — just YAML structures that map cleanly to Pydantic models.
- The `VesselOntologyService` is Ship's Computer infrastructure (no sovereign identity, no callsign, no personality).
- Keep it lean. The ontology is a queryable data model, not a knowledge graph engine. Python dicts/dataclasses in memory, SQLite for persistence.

---

## Step 1: Schema YAML Files

Create `config/ontology/` directory with three schema files.

### `config/ontology/vessel.yaml`

```yaml
# Domain 1: Vessel — the platform itself
vessel:
  identity:
    name: "ProbOS"
    version: "0.4.0"
    description: "AI Agent Orchestration Platform"
    instance_id: null  # Generated at first boot, persisted
  alert_conditions:
    - GREEN    # Normal operations
    - YELLOW   # Degraded, heightened monitoring
    - RED      # Critical, emergency protocols
  default_alert_condition: GREEN
```

### `config/ontology/organization.yaml`

Define departments and posts (billets). Posts exist independent of who fills them (W3C ORG pattern). The `reports_to` field defines chain of command.

```yaml
# Domain 2: Organization — departments, posts, chain of command
departments:
  - id: bridge
    name: "Bridge"
    description: "Command and advisory staff"
  - id: engineering
    name: "Engineering"
    description: "Systems development, maintenance, and optimization"
  - id: science
    name: "Science"
    description: "Research, analysis, and exploration"
  - id: medical
    name: "Medical"
    description: "Crew health, cognitive diagnostics, treatment"
  - id: security
    name: "Security"
    description: "Threat detection, access control, system integrity"
  - id: operations
    name: "Operations"
    description: "Operational readiness, resource management, logistics"

posts:
  # Bridge
  - id: captain
    title: "Captain"
    department: bridge
    reports_to: null  # Top of chain
    authority_over: [first_officer, counselor]
    tier: external  # Human, not agent
  - id: first_officer
    title: "First Officer"
    department: bridge
    reports_to: captain
    authority_over: [chief_engineer, chief_science, chief_medical, chief_security, chief_operations]
    tier: crew
  - id: counselor
    title: "Ship's Counselor"
    department: bridge
    reports_to: captain
    authority_over: []
    tier: crew

  # Engineering
  - id: chief_engineer
    title: "Chief Engineer"
    department: engineering
    reports_to: first_officer
    authority_over: [engineering_officer, builder_officer]
    tier: crew
  - id: engineering_officer
    title: "Engineering Officer"
    department: engineering
    reports_to: chief_engineer
    authority_over: []
    tier: crew
  - id: builder_officer
    title: "Builder"
    department: engineering
    reports_to: chief_engineer
    authority_over: []
    tier: crew

  # Science
  - id: chief_science
    title: "Chief Science Officer"
    department: science
    reports_to: first_officer
    authority_over: [scout_officer]
    tier: crew
    note: "Number One is dual-hatted as First Officer and Chief Science Officer"
  - id: scout_officer
    title: "Scout"
    department: science
    reports_to: chief_science
    authority_over: []
    tier: crew

  # Medical
  - id: chief_medical
    title: "Chief Medical Officer"
    department: medical
    reports_to: first_officer
    authority_over: [surgeon_officer, pharmacist_officer, pathologist_officer]
    tier: crew
  - id: surgeon_officer
    title: "Surgeon"
    department: medical
    reports_to: chief_medical
    authority_over: []
    tier: crew
  - id: pharmacist_officer
    title: "Pharmacist"
    department: medical
    reports_to: chief_medical
    authority_over: []
    tier: crew
  - id: pathologist_officer
    title: "Pathologist"
    department: medical
    reports_to: chief_medical
    authority_over: []
    tier: crew

  # Security
  - id: chief_security
    title: "Chief of Security"
    department: security
    reports_to: first_officer
    authority_over: []
    tier: crew

  # Operations
  - id: chief_operations
    title: "Chief of Operations"
    department: operations
    reports_to: first_officer
    authority_over: []
    tier: crew

# Agent-to-post assignments (which agent_type fills which post)
assignments:
  - agent_type: architect
    post_id: first_officer
    callsign: "Number One"
  - agent_type: counselor
    post_id: counselor
    callsign: "Troi"
  - agent_type: engineering_officer
    post_id: chief_engineer
    callsign: "LaForge"
  - agent_type: builder
    post_id: builder_officer
    callsign: "Scotty"
  - agent_type: scout
    post_id: scout_officer
    callsign: "Wesley"
  - agent_type: diagnostician
    post_id: chief_medical
    callsign: "Bones"
  - agent_type: surgeon
    post_id: surgeon_officer
    callsign: "Pulaski"
  - agent_type: pharmacist
    post_id: pharmacist_officer
    callsign: "Ogawa"
  - agent_type: pathologist
    post_id: pathologist_officer
    callsign: "Selar"
  - agent_type: security_officer
    post_id: chief_security
    callsign: "Worf"
  - agent_type: operations_officer
    post_id: chief_operations
    callsign: "O'Brien"
```

### `config/ontology/crew.yaml`

Agent identity schema. This defines what fields exist for crew agents — actual values come from crew_profiles/ YAML and runtime state.

```yaml
# Domain 3: Crew — agent identity schema
#
# This schema defines the STRUCTURE of crew identity.
# Actual agent data is populated at runtime from:
#   - crew_profiles/*.yaml (personality, callsign)
#   - TrustNetwork (trust_score)
#   - EarnedAgency (rank)
#   - ACM (lifecycle_state)
#   - ModelRegistry (model_id)

agent_identity:
  fields:
    - name: agent_id
      type: string
      description: "Unique runtime identifier"
    - name: agent_type
      type: string
      description: "Agent type key (e.g. 'security_officer')"
    - name: callsign
      type: string
      description: "Human-readable name (e.g. 'Worf')"
    - name: tier
      type: enum
      values: [crew, utility, infrastructure]
      description: "AD-398 three-tier classification"

agent_state:
  fields:
    - name: lifecycle_state
      type: enum
      values: [registered, probationary, active, suspended, decommissioned]
      description: "ACM lifecycle state"
    - name: rank
      type: enum
      values: [ensign, lieutenant, commander, senior_officer]
      description: "Earned Agency rank from trust score"
    - name: trust_score
      type: float
      description: "Current trust network score [0.0, 1.0]"
    - name: confidence
      type: float
      description: "Agent confidence from recent outcomes"

agent_character:
  description: "Personality traits (Big Five) — seeded from crew_profiles/*.yaml, evolve over time"
  fields:
    - name: openness
      type: float
    - name: conscientiousness
      type: float
    - name: extraversion
      type: float
    - name: agreeableness
      type: float
    - name: neuroticism
      type: float
```

---

## Step 2: VesselOntologyService

Create `src/probos/ontology.py` — the Ship's Computer service that loads schema YAML, builds in-memory graph, and provides query methods.

### Class: `VesselOntologyService`

```python
class VesselOntologyService:
    """Ship's Computer service — unified formal model of the vessel.

    Loads ontology schema from config/ontology/*.yaml, builds in-memory
    graph at startup, provides query methods for runtime use.

    Infrastructure service (no sovereign identity).
    """
```

### Data Models (Pydantic or dataclasses)

Define these in `ontology.py`:

```python
@dataclass
class Department:
    id: str
    name: str
    description: str

@dataclass
class Post:
    id: str
    title: str
    department_id: str
    reports_to: str | None  # post_id
    authority_over: list[str]  # post_ids
    tier: str  # "crew", "utility", "infrastructure", "external"

@dataclass
class Assignment:
    agent_type: str
    post_id: str
    callsign: str
    agent_id: str | None = None  # Filled at runtime when agent wires

@dataclass
class VesselIdentity:
    name: str
    version: str
    description: str
    instance_id: str  # UUID, generated once, persisted
    started_at: float  # time.time() at boot

@dataclass
class VesselState:
    alert_condition: str  # GREEN, YELLOW, RED
    uptime_seconds: float
    active_crew_count: int
```

### Constructor / Loading

```python
def __init__(self, config_dir: Path):
    self._config_dir = config_dir
    self._departments: dict[str, Department] = {}
    self._posts: dict[str, Post] = {}
    self._assignments: dict[str, Assignment] = {}  # keyed by agent_type
    self._vessel_identity: VesselIdentity | None = None
    self._alert_condition: str = "GREEN"
    self._instance_id: str | None = None

async def initialize(self) -> None:
    """Load YAML schemas and build in-memory graph."""
    # Load vessel.yaml → VesselIdentity
    # Load organization.yaml → departments, posts, assignments
    # crew.yaml is structural schema only — actual data comes from runtime
    # Generate instance_id if not persisted
```

### Key Query Methods

These are the methods the runtime and agents will use:

```python
# Vessel queries
def get_vessel_identity(self) -> VesselIdentity: ...
def get_vessel_state(self) -> VesselState: ...
def get_alert_condition(self) -> str: ...
def set_alert_condition(self, condition: str) -> None: ...

# Organization queries
def get_departments(self) -> list[Department]: ...
def get_department(self, dept_id: str) -> Department | None: ...
def get_posts(self, department_id: str | None = None) -> list[Post]: ...
def get_post(self, post_id: str) -> Post | None: ...
def get_chain_of_command(self, post_id: str) -> list[Post]:
    """Walk reports_to chain from post up to captain. Returns [self, ..., captain]."""
def get_direct_reports(self, post_id: str) -> list[Post]:
    """Posts that report to this post."""

# Assignment queries
def get_assignment_for_agent(self, agent_type: str) -> Assignment | None: ...
def get_agent_department(self, agent_type: str) -> str | None:
    """Return department_id for an agent_type. Replaces _AGENT_DEPARTMENTS dict."""
def get_crew_agent_types(self) -> set[str]:
    """Return set of agent_types assigned to crew-tier posts. Replaces _WARD_ROOM_CREW."""
def get_post_for_agent(self, agent_type: str) -> Post | None: ...

# Wire agent_id to assignment at runtime (called during agent wiring)
def wire_agent(self, agent_type: str, agent_id: str) -> None:
    """Associate a runtime agent_id with its post assignment."""

# Crew identity assembly (for context injection)
def get_crew_context(self, agent_type: str) -> dict:
    """Assemble full crew context for an agent — post, department, chain of command,
    peers, reports. Used by _gather_context() in proactive loop."""
```

### `get_crew_context()` Detail

This is the key method for agent grounding. Returns a dict like:

```python
{
    "vessel": {"name": "ProbOS", "version": "0.4.0", "alert_condition": "GREEN"},
    "identity": {"agent_type": "security_officer", "callsign": "Worf", "post": "Chief of Security"},
    "department": {"id": "security", "name": "Security"},
    "chain_of_command": ["Chief of Security", "First Officer", "Captain"],
    "reports_to": "First Officer (Number One)",
    "direct_reports": [],
    "peers": [  # Other crew in same department
    ],
    "adjacent_departments": ["Engineering", "Operations"],  # Departments of posts this post's superior also commands
}
```

### Instance ID Persistence

Generate a UUID on first boot. Persist to `data_dir/ontology/instance_id` (simple text file). Load on subsequent boots. This gives each ProbOS instance a stable identity across restarts.

---

## Step 3: Wire into Runtime

### `runtime.py` changes

1. **Instantiate service** in `ProbOSRuntime.__init__()`:
   ```python
   self.ontology: VesselOntologyService | None = None
   ```

2. **Initialize** during startup (after config loading, before agent wiring):
   ```python
   ontology_dir = Path(self._config_dir) / "ontology" if self._config_dir else None
   if ontology_dir and ontology_dir.exists():
       from probos.ontology import VesselOntologyService
       self.ontology = VesselOntologyService(ontology_dir)
       await self.ontology.initialize()
   ```

3. **Wire agents** — after each agent is wired into the mesh, call:
   ```python
   if self.ontology:
       self.ontology.wire_agent(agent.agent_type, agent.id)
   ```

4. **Do NOT replace** `_WARD_ROOM_CREW` or `_AGENT_DEPARTMENTS` yet. They stay for now. The ontology service runs alongside them. Future migration AD will swap callers.

### `api.py` changes

Add REST endpoints:

```python
@app.get("/api/ontology/vessel")
async def get_vessel():
    """Vessel identity and state."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, 503)
    return {
        "identity": asdict(runtime.ontology.get_vessel_identity()),
        "state": asdict(runtime.ontology.get_vessel_state()),
    }

@app.get("/api/ontology/organization")
async def get_organization():
    """Full org chart: departments, posts, assignments, chain of command."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, 503)
    ont = runtime.ontology
    return {
        "departments": [asdict(d) for d in ont.get_departments()],
        "posts": [asdict(p) for p in ont.get_posts()],
        "assignments": [asdict(a) for a in ont._assignments.values()],
    }

@app.get("/api/ontology/crew/{agent_type}")
async def get_crew_member(agent_type: str):
    """Agent's full ontology context — identity, post, department, chain of command."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, 503)
    ctx = runtime.ontology.get_crew_context(agent_type)
    if not ctx:
        return JSONResponse({"error": "Agent not found in ontology"}, 404)
    return ctx
```

---

## Step 4: Context Injection (Proactive Loop)

In `proactive.py` `_gather_context()`, add ontology context for crew agents:

```python
# Ontology context (AD-429a)
if hasattr(rt, 'ontology') and rt.ontology:
    crew_ctx = rt.ontology.get_crew_context(agent.agent_type)
    if crew_ctx:
        context["ontology"] = crew_ctx
```

This gives every agent, during every proactive think, a formal description of who they are, where they fit, and what the vessel is. This is the primary anti-Troi-problem mechanism.

---

## Step 5: Tests

Create `tests/test_ontology.py` with:

1. **Schema loading** — Load all three YAML files, verify parsing
2. **Department queries** — `get_departments()`, `get_department("security")`
3. **Post queries** — `get_posts()`, `get_posts(department_id="medical")`, `get_post("chief_security")`
4. **Chain of command** — `get_chain_of_command("chief_security")` returns `[chief_security, first_officer, captain]`
5. **Direct reports** — `get_direct_reports("first_officer")` returns all department chiefs
6. **Assignment lookups** — `get_assignment_for_agent("security_officer")` returns Worf
7. **Agent department** — `get_agent_department("security_officer")` returns "security"
8. **Crew set** — `get_crew_agent_types()` returns all crew agent types (replaces `_WARD_ROOM_CREW`)
9. **Wire agent** — `wire_agent("security_officer", "abc123")` then verify assignment.agent_id is set
10. **Crew context assembly** — `get_crew_context("security_officer")` returns full context dict with vessel, identity, department, chain of command
11. **Vessel identity** — `get_vessel_identity()` returns name, version, instance_id
12. **Alert condition** — default is GREEN, `set_alert_condition("YELLOW")` changes it
13. **Unknown agent** — `get_crew_context("nonexistent")` returns None
14. **Instance ID persistence** — generate, save, reload, verify same UUID

---

## Verification

1. `uv run pytest tests/test_ontology.py -v` — all ontology tests pass
2. `uv run pytest` — full suite passes (no regressions)
3. `cd ui && npm run build` — frontend still builds (no TS changes in this AD)
4. Manual: `curl http://127.0.0.1:18900/api/ontology/vessel` returns vessel identity
5. Manual: `curl http://127.0.0.1:18900/api/ontology/organization` returns full org chart
6. Manual: `curl http://127.0.0.1:18900/api/ontology/crew/security_officer` returns Worf's full context

---

## Files

| File | Action |
|------|--------|
| `config/ontology/vessel.yaml` | **NEW** — Vessel domain schema |
| `config/ontology/organization.yaml` | **NEW** — Organization domain with departments, posts, assignments |
| `config/ontology/crew.yaml` | **NEW** — Crew identity schema (structural) |
| `src/probos/ontology.py` | **NEW** — VesselOntologyService |
| `src/probos/runtime.py` | **MODIFY** — Instantiate + initialize ontology service, wire agents |
| `src/probos/api.py` | **MODIFY** — Add 3 REST endpoints |
| `src/probos/proactive.py` | **MODIFY** — Add ontology context to `_gather_context()` |
| `tests/test_ontology.py` | **NEW** — 14+ tests |
