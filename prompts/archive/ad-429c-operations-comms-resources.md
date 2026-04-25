# AD-429c: Operations, Communication & Resources Ontology Domains

## Context

AD-429a delivered Vessel + Organization + Crew domains. AD-429b delivered the Skills domain. The `VesselOntologyService` in `src/probos/ontology.py` (527 lines) loads YAML schemas from `config/ontology/`, builds in-memory models, and provides query methods. The pattern is established: dataclasses + YAML schema + `_load_*()` method + query methods + optional `get_crew_context()` extension.

AD-429c completes the core ontology model with three domains:
1. **Operations** — formalizes duties, standing orders, watch rotation, alert condition procedures
2. **Communication** — formalizes channel types, thread modes, message patterns
3. **Resources** — formalizes model tiers, tool capabilities, knowledge sources

These domains have existing runtime implementations that are **not being replaced**. The ontology provides a unified formal schema alongside them — the same coexistence pattern used in 429a/429b.

## Important Constraints

- The ontology is a **queryable schema**, not a replacement engine. `ward_room.py`, `watch_rotation.py`, `duty_schedule.py`, `standing_orders.py`, and `CognitiveConfig` all stay as-is. The ontology defines what these systems ARE so agents can reason about them.
- Do NOT modify `ward_room.py`, `watch_rotation.py`, `duty_schedule.py`, or `standing_orders.py`. Only extend `ontology.py`.
- Keep it lean — these are three domains in one AD. Each domain should be 1 YAML file + dataclasses + query methods. No SQLite, no async, no complex persistence.
- Follow the established pattern from 429a/429b exactly.

---

## Step 1: Operations Schema — `config/ontology/operations.yaml`

The Operations domain formalizes three existing systems: the duty schedule, watch rotation, and standing orders — plus alert condition procedures that connect to the existing `VesselState.alert_condition`.

```yaml
# Domain 5: Operations — duties, watches, standing orders, alert procedures
#
# Formalizes existing systems:
#   - DutyScheduleConfig (config.py) — duty definitions per agent type
#   - WatchManager (watch_rotation.py) — watch types, standing tasks, duty shifts
#   - StandingOrders (standing_orders.py) — 6-tier instruction composition
#   - VesselState.alert_condition (ontology vessel domain) — GREEN/YELLOW/RED

standing_order_tiers:
  - tier: 1
    name: "Agent Identity"
    source: "Agent class instructions"
    scope: "individual"
    mutable: false
    description: "Hardcoded identity from the agent's Python class"
  - tier: 1.5
    name: "Crew Personality"
    source: "config/standing_orders/crew_profiles/*.yaml"
    scope: "individual"
    mutable: false
    description: "Big Five personality traits mapped to behavioral guidance (AD-393)"
  - tier: 2
    name: "Federation Constitution"
    source: "config/standing_orders/federation.md"
    scope: "universal"
    mutable: false
    description: "Immutable principles — Westworld Principle, Core Directives, Safety Budget"
  - tier: 3
    name: "Ship Standing Orders"
    source: "config/standing_orders/ship.md"
    scope: "ship"
    mutable: true
    description: "Instance-level conventions — import patterns, testing standards"
  - tier: 4
    name: "Department Protocols"
    source: "config/standing_orders/{department}.md"
    scope: "department"
    mutable: true
    description: "Department-specific standards — build pipeline (engineering), review checklists"
  - tier: 5
    name: "Agent Standing Orders"
    source: "config/standing_orders/{agent_type}.md"
    scope: "individual"
    mutable: true
    description: "Learned practices from dream consolidation, self-modification pipeline"
  - tier: 6
    name: "Active Directives"
    source: "DirectiveStore (runtime)"
    scope: "individual"
    mutable: true
    description: "Runtime directives from Captain or chain of command (AD-386)"

watch_types:
  - id: alpha
    name: "Alpha Watch"
    description: "Full operations — all crew active, all systems monitored"
    staffing: full
  - id: beta
    name: "Beta Watch"
    description: "Reduced operations — essential crew only, routine monitoring"
    staffing: reduced
  - id: gamma
    name: "Gamma Watch"
    description: "Maintenance/background — minimal crew, background tasks only"
    staffing: minimal

# Alert condition procedures — what changes operationally at each level
alert_procedures:
  GREEN:
    description: "Normal operations"
    watch_default: alpha
    proactive_interval: normal
    escalation_threshold: standard
  YELLOW:
    description: "Degraded state or heightened monitoring"
    watch_default: alpha
    proactive_interval: increased
    escalation_threshold: lowered
    actions:
      - "Increase proactive think frequency"
      - "Lower bridge alert threshold"
      - "Enable additional monitoring agents"
  RED:
    description: "Critical emergency — all hands"
    watch_default: alpha
    proactive_interval: maximum
    escalation_threshold: minimum
    actions:
      - "All crew active regardless of watch assignment"
      - "Proactive thinks at maximum frequency"
      - "All bridge alerts immediate"
      - "Captain notified immediately"

# Duty categories — taxonomy of duty types across departments
duty_categories:
  - id: monitoring
    name: "Monitoring & Observation"
    description: "Regular system health checks, status reports"
    examples: ["systems_check", "crew_health_check", "security_audit", "ops_status"]
  - id: analysis
    name: "Analysis & Review"
    description: "Deep analysis of patterns, code, proposals"
    examples: ["architecture_review", "code_review", "wellness_review"]
  - id: reporting
    name: "Reporting & Communication"
    description: "Status reports, recommendations, Ward Room posts"
    examples: ["scout_report", "department_briefing"]
  - id: maintenance
    name: "Maintenance & Operations"
    description: "Routine operational tasks, cleanup, optimization"
    examples: ["build_pipeline", "index_refresh", "log_rotation"]
```

---

## Step 2: Communication Schema — `config/ontology/communication.yaml`

Formalizes the Ward Room's channel types, thread modes, and interaction patterns.

```yaml
# Domain 6: Communication — channels, thread modes, message patterns
#
# Formalizes existing systems:
#   - WardRoomService (ward_room.py) — channels, threads, posts, endorsements
#   - WardRoomConfig (config.py) — cooldowns, retention, responder caps
#   - AD-424 (Thread Classification) — inform/discuss/action modes
#   - AD-437 (Action Space) — structured agent actions in Ward Room

channel_types:
  - id: ship
    name: "Ship-wide"
    description: "All crew can see and participate"
    examples: ["All Hands", "Improvement Proposals"]
    default_mode: discuss
  - id: department
    name: "Department"
    description: "Scoped to a single department's crew"
    examples: ["Medical", "Engineering", "Security", "Science", "Operations", "Bridge"]
    default_mode: discuss
  - id: dm
    name: "Direct Message"
    description: "Private 1:1 conversation between two participants"
    default_mode: discuss
  - id: custom
    name: "Custom"
    description: "User-created channels with custom membership"
    default_mode: discuss

thread_modes:
  - id: inform
    name: "Inform"
    description: "Informational — no reply expected. Used for announcements, alerts, system messages."
    reply_expected: false
    routing: none
    use_cases: ["bridge alerts", "system announcements", "status updates"]
  - id: discuss
    name: "Discuss"
    description: "Open discussion — all eligible crew can respond within responder cap."
    reply_expected: true
    routing: department_preference
    use_cases: ["proposals", "observations", "general discussion"]
  - id: action
    name: "Action"
    description: "Action-oriented — responses should propose or commit to concrete actions."
    reply_expected: true
    routing: competency_based
    use_cases: ["incident response", "task coordination", "decision requests"]
  - id: announce
    name: "Announce"
    description: "System or Captain announcements — crew may respond but thread is primarily informational."
    reply_expected: false
    routing: none
    use_cases: ["restart announcements", "Captain's orders", "system events"]

# Message patterns — the interaction vocabulary
message_patterns:
  - id: observation
    tag: "[Observation]"
    description: "Agent shares an analysis or finding from their domain expertise"
    expected_from: all_crew
    typical_response: discuss
  - id: proposal
    tag: "[Proposal]"
    description: "Agent proposes a change, improvement, or action"
    expected_from: all_crew
    typical_response: discuss
    structured_fields: ["title", "rationale", "affected_systems", "priority"]
  - id: endorsement
    tag: "[ENDORSE post_id UP/DOWN]"
    description: "Agent endorses or opposes a post (AD-437 action space)"
    expected_from: lieutenant_plus
    min_rank: lieutenant
  - id: reply
    tag: "[REPLY thread_id]...[/REPLY]"
    description: "Agent posts a structured reply to a specific thread (AD-437 action space)"
    expected_from: lieutenant_plus
    min_rank: lieutenant
  - id: no_response
    tag: "[NO_RESPONSE]"
    description: "Agent explicitly declines to respond — disciplined silence"
    expected_from: all_crew

# Credibility system
credibility:
  description: "Rolling credibility score (0-1) based on posting quality and endorsement history"
  min_channel_creation: 0.3
  factors:
    - "Post endorsement ratio (upvotes vs downvotes)"
    - "Total post count"
    - "Total endorsements received"
```

---

## Step 3: Resources Schema — `config/ontology/resources.yaml`

Formalizes LLM model tiers, tool capabilities (conceptual — no ToolRegistry exists yet), and knowledge sources.

```yaml
# Domain 7: Resources — models, tools, knowledge sources
#
# Formalizes existing systems:
#   - CognitiveConfig (config.py) — 3-tier LLM model system
#   - KnowledgeStore (knowledge/store.py) — operational state persistence
#   - EpisodicMemory — agent experience store
#   - AD-434 Ship's Records — formalized in AD-429d (Records domain)
#
# Note: ToolRegistry (AD-423) does not yet exist in code.
# This schema defines the conceptual model for when it does.

model_tiers:
  - id: fast
    name: "Fast"
    description: "Quick, low-cost operations — routing, classification, simple generation"
    default_model: "gpt-4o-mini"
    use_cases: ["intent routing", "classification", "simple responses", "triage"]
    cost: low
    latency: low
  - id: standard
    name: "Standard"
    description: "General-purpose operations — most agent reasoning"
    default_model: "claude-sonnet-4"
    use_cases: ["proactive thinks", "code review", "analysis", "Ward Room responses"]
    cost: medium
    latency: medium
  - id: deep
    name: "Deep"
    description: "Complex reasoning — architecture decisions, deep analysis"
    default_model: "claude-sonnet-4"
    use_cases: ["architecture review", "complex debugging", "self-modification proposals", "dream consolidation"]
    cost: high
    latency: high

# Model assignment — which tier each agent/function uses
# Actual runtime config is in CognitiveConfig. This documents the design intent.
model_assignments:
  proactive_think: standard
  duty_execution: standard
  dream_consolidation: deep
  intent_routing: fast
  chat_response: standard
  code_generation: deep
  endorsement_extraction: fast

# Tool capabilities — conceptual taxonomy
# These are capabilities an agent can invoke, not a runtime registry.
# AD-423 (Tool Registry) will implement the runtime version.
tool_capabilities:
  - id: codebase_query
    name: "Codebase Query"
    description: "Search and analyze the codebase via CodebaseIndex"
    provider: ship_computer
    available_to: all_crew
  - id: ward_room_post
    name: "Ward Room Post"
    description: "Post to Ward Room channels"
    provider: ward_room
    available_to: all_crew
    gated_by: earned_agency
  - id: ward_room_endorse
    name: "Ward Room Endorse"
    description: "Endorse or oppose a Ward Room post"
    provider: ward_room
    available_to: lieutenant_plus
    gated_by: earned_agency
  - id: ward_room_reply
    name: "Ward Room Reply"
    description: "Reply to a specific Ward Room thread"
    provider: ward_room
    available_to: lieutenant_plus
    gated_by: earned_agency
  - id: self_modification
    name: "Self-Modification Proposal"
    description: "Propose changes to own standing orders via dream consolidation"
    provider: dreaming_engine
    available_to: all_crew
    gated_by: trust_threshold
  - id: knowledge_query
    name: "Knowledge Query"
    description: "Query the ship's knowledge store"
    provider: ship_computer
    available_to: all_crew
  - id: episodic_recall
    name: "Episodic Recall"
    description: "Recall own episodic memories"
    provider: ship_computer
    available_to: all_crew
    scope: own_shard_only

# Knowledge source types
knowledge_sources:
  - id: episodic_memory
    name: "Episodic Memory"
    description: "Per-agent experience store — sovereign shard, private diary"
    tier: 1
    tier_name: "Experience"
    storage: chromadb
    access: own_shard_only
  - id: ship_records
    name: "Ship's Records"
    description: "Git-backed instance knowledge — duty logs, notebooks, published reports"
    tier: 2
    tier_name: "Records"
    storage: git
    access: all_crew
    note: "AD-434 — not yet implemented. Placeholder for AD-429d."
  - id: knowledge_store
    name: "Knowledge Store"
    description: "Operational state persistence — trust snapshots, routing weights, agent source"
    tier: 3
    tier_name: "Operational State"
    storage: git_repo
    access: ship_computer
    note: "Despite the name, this is NOT a shared knowledge library. It's infrastructure state."
```

---

## Step 4: Data Models in `ontology.py`

Add dataclasses for each domain. Keep them simple — these are schema representations, not runtime engines.

### Operations Models

```python
@dataclass
class StandingOrderTier:
    """One tier of the standing orders hierarchy."""
    tier: float  # 1, 1.5, 2, 3, 4, 5, 6
    name: str
    source: str
    scope: str  # "universal", "ship", "department", "individual"
    mutable: bool
    description: str

@dataclass
class WatchTypeSchema:
    """Watch type definition from ontology."""
    id: str  # "alpha", "beta", "gamma"
    name: str
    description: str
    staffing: str  # "full", "reduced", "minimal"

@dataclass
class AlertProcedure:
    """Operational procedures for an alert condition level."""
    condition: str  # "GREEN", "YELLOW", "RED"
    description: str
    watch_default: str
    proactive_interval: str
    escalation_threshold: str
    actions: list[str]

@dataclass
class DutyCategory:
    """Category grouping for duty types."""
    id: str
    name: str
    description: str
    examples: list[str]
```

### Communication Models

```python
@dataclass
class ChannelTypeSchema:
    """Channel type definition from ontology."""
    id: str  # "ship", "department", "dm", "custom"
    name: str
    description: str
    default_mode: str

@dataclass
class ThreadModeSchema:
    """Thread mode definition from ontology."""
    id: str  # "inform", "discuss", "action", "announce"
    name: str
    description: str
    reply_expected: bool
    routing: str  # "none", "department_preference", "competency_based"
    use_cases: list[str]

@dataclass
class MessagePattern:
    """Structured message pattern used in Ward Room communication."""
    id: str
    tag: str
    description: str
    expected_from: str
    min_rank: str | None = None
```

### Resources Models

```python
@dataclass
class ModelTier:
    """LLM model tier definition."""
    id: str  # "fast", "standard", "deep"
    name: str
    description: str
    default_model: str
    use_cases: list[str]

@dataclass
class ToolCapability:
    """A capability an agent can invoke."""
    id: str
    name: str
    description: str
    provider: str
    available_to: str  # "all_crew", "lieutenant_plus", etc.
    gated_by: str | None = None

@dataclass
class KnowledgeSourceSchema:
    """Knowledge source type in the three-tier knowledge model."""
    id: str
    name: str
    description: str
    tier: int
    tier_name: str
    storage: str
    access: str
```

---

## Step 5: VesselOntologyService Extensions

### New Instance Variables

Add to `__init__()`:

```python
# Operations domain (AD-429c)
self._standing_order_tiers: list[StandingOrderTier] = []
self._watch_types: list[WatchTypeSchema] = []
self._alert_procedures: dict[str, AlertProcedure] = {}
self._duty_categories: list[DutyCategory] = []

# Communication domain (AD-429c)
self._channel_types: list[ChannelTypeSchema] = []
self._thread_modes: list[ThreadModeSchema] = []
self._message_patterns: list[MessagePattern] = []

# Resources domain (AD-429c)
self._model_tiers: list[ModelTier] = []
self._tool_capabilities: list[ToolCapability] = []
self._knowledge_sources: list[KnowledgeSourceSchema] = []
```

### Loading Methods

Add three `_load_*()` methods following the exact pattern of `_load_skills_schema()`:

```python
def _load_operations_schema(self, path: Path) -> None:
    """Load operations.yaml — standing order tiers, watch types, alert procedures, duties."""
    # Parse standing_order_tiers list → StandingOrderTier objects
    # Parse watch_types list → WatchTypeSchema objects
    # Parse alert_procedures dict → AlertProcedure objects
    # Parse duty_categories list → DutyCategory objects

def _load_communication_schema(self, path: Path) -> None:
    """Load communication.yaml — channel types, thread modes, message patterns."""
    # Parse channel_types list → ChannelTypeSchema objects
    # Parse thread_modes list → ThreadModeSchema objects
    # Parse message_patterns list → MessagePattern objects

def _load_resources_schema(self, path: Path) -> None:
    """Load resources.yaml — model tiers, tool capabilities, knowledge sources."""
    # Parse model_tiers list → ModelTier objects
    # Parse tool_capabilities list → ToolCapability objects
    # Parse knowledge_sources list → KnowledgeSourceSchema objects
```

Call all three from `initialize()` after the existing `_load_skills_schema()` call:

```python
for name, loader in [
    ("operations.yaml", self._load_operations_schema),
    ("communication.yaml", self._load_communication_schema),
    ("resources.yaml", self._load_resources_schema),
]:
    path = self._config_dir / name
    if path.exists():
        loader(path)
```

### Query Methods

```python
# --- Operations queries ---
def get_standing_order_tiers(self) -> list[StandingOrderTier]:
    """Get the standing orders tier hierarchy."""
    return list(self._standing_order_tiers)

def get_watch_types(self) -> list[WatchTypeSchema]:
    """Get all watch type definitions."""
    return list(self._watch_types)

def get_alert_procedure(self, condition: str) -> AlertProcedure | None:
    """Get operational procedures for an alert condition level."""
    return self._alert_procedures.get(condition)

def get_duty_categories(self) -> list[DutyCategory]:
    """Get duty category taxonomy."""
    return list(self._duty_categories)

# --- Communication queries ---
def get_channel_types(self) -> list[ChannelTypeSchema]:
    """Get all channel type definitions."""
    return list(self._channel_types)

def get_thread_modes(self) -> list[ThreadModeSchema]:
    """Get all thread mode definitions."""
    return list(self._thread_modes)

def get_thread_mode(self, mode_id: str) -> ThreadModeSchema | None:
    """Get a specific thread mode definition."""
    for tm in self._thread_modes:
        if tm.id == mode_id:
            return tm
    return None

def get_message_patterns(self) -> list[MessagePattern]:
    """Get all message pattern definitions."""
    return list(self._message_patterns)

# --- Resources queries ---
def get_model_tiers(self) -> list[ModelTier]:
    """Get all LLM model tier definitions."""
    return list(self._model_tiers)

def get_model_tier(self, tier_id: str) -> ModelTier | None:
    """Get a specific model tier (fast/standard/deep)."""
    for mt in self._model_tiers:
        if mt.id == tier_id:
            return mt
    return None

def get_tool_capabilities(self, available_to: str | None = None) -> list[ToolCapability]:
    """Get tool capabilities, optionally filtered by access level."""
    if available_to is None:
        return list(self._tool_capabilities)
    return [t for t in self._tool_capabilities if t.available_to == available_to]

def get_knowledge_sources(self) -> list[KnowledgeSourceSchema]:
    """Get the three-tier knowledge source model."""
    return list(self._knowledge_sources)
```

### Extend `get_crew_context()`

Add operations and communication context to the crew context dict returned by `get_crew_context()`:

```python
# Operations context (AD-429c)
if self._alert_procedures:
    context["alert_condition"] = self._alert_condition
    proc = self.get_alert_procedure(self._alert_condition)
    if proc:
        context["alert_procedure"] = proc.description

# Communication context (AD-429c)
if self._message_patterns:
    context["available_actions"] = [
        {"tag": p.tag, "description": p.description}
        for p in self._message_patterns
        if p.min_rank is None  # Agent-specific filtering would need rank
    ]
```

Keep it minimal — don't dump all three domains into every agent's context. Just the operationally relevant bits: current alert level and available communication actions.

---

## Step 6: REST API Endpoints

Add to `api.py`:

```python
@app.get("/api/ontology/operations")
async def get_ontology_operations():
    """Operations domain — standing order tiers, watch types, alert procedures, duties."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, 503)
    ont = runtime.ontology
    return {
        "standing_order_tiers": [asdict(t) for t in ont.get_standing_order_tiers()],
        "watch_types": [asdict(w) for w in ont.get_watch_types()],
        "alert_procedures": {k: asdict(v) for k, v in ont._alert_procedures.items()},
        "duty_categories": [asdict(d) for d in ont.get_duty_categories()],
    }

@app.get("/api/ontology/communication")
async def get_ontology_communication():
    """Communication domain — channel types, thread modes, message patterns."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, 503)
    ont = runtime.ontology
    return {
        "channel_types": [asdict(c) for c in ont.get_channel_types()],
        "thread_modes": [asdict(t) for t in ont.get_thread_modes()],
        "message_patterns": [asdict(m) for m in ont.get_message_patterns()],
    }

@app.get("/api/ontology/resources")
async def get_ontology_resources():
    """Resources domain — model tiers, tool capabilities, knowledge sources."""
    if not runtime.ontology:
        return JSONResponse({"error": "Ontology not initialized"}, 503)
    ont = runtime.ontology
    return {
        "model_tiers": [asdict(m) for m in ont.get_model_tiers()],
        "tool_capabilities": [asdict(t) for t in ont.get_tool_capabilities()],
        "knowledge_sources": [asdict(k) for k in ont.get_knowledge_sources()],
    }
```

---

## Step 7: Tests

Create `tests/test_ontology_ops_comms_resources.py` with:

**Operations (8 tests):**
1. Load operations.yaml — verify parsing succeeds
2. Standing order tiers — 7 tiers loaded (1, 1.5, 2, 3, 4, 5, 6)
3. Standing order tier mutability — tiers 1, 1.5, 2 immutable; 3, 4, 5, 6 mutable
4. Watch types — 3 types: alpha, beta, gamma
5. Alert procedure GREEN — returns description, watch_default, no actions
6. Alert procedure RED — returns description with 4 action items
7. Alert procedure unknown — returns None
8. Duty categories — 4 categories loaded

**Communication (7 tests):**
9. Load communication.yaml — verify parsing succeeds
10. Channel types — 4 types: ship, department, dm, custom
11. Thread modes — 4 modes: inform, discuss, action, announce
12. Thread mode query — `get_thread_mode("discuss")` returns correct fields
13. Thread mode unknown — `get_thread_mode("debate")` returns None
14. Message patterns — at least 5 patterns loaded
15. Message pattern min_rank — endorsement and reply patterns have min_rank="lieutenant"

**Resources (7 tests):**
16. Load resources.yaml — verify parsing succeeds
17. Model tiers — 3 tiers: fast, standard, deep
18. Model tier query — `get_model_tier("fast")` returns correct default model
19. Model tier unknown — `get_model_tier("extreme")` returns None
20. Tool capabilities all — returns full list
21. Tool capabilities filtered — `get_tool_capabilities("all_crew")` returns subset
22. Knowledge sources — 3 sources with correct tier assignments (1, 2, 3)

**Integration (3 tests):**
23. Full initialize loads all domains — all counts > 0
24. Crew context includes alert info — `get_crew_context()` has `alert_condition` key
25. Crew context includes available actions — `get_crew_context()` has `available_actions` key

---

## Verification

1. `uv run pytest tests/test_ontology_ops_comms_resources.py -v` — all 25 tests pass
2. `uv run pytest tests/test_ontology.py tests/test_ontology_skills.py -v` — existing ontology tests pass
3. `uv run pytest` — full suite passes (no regressions)
4. `cd ui && npm run build` — frontend still builds
5. Manual: `curl http://127.0.0.1:18900/api/ontology/operations` returns full ops domain
6. Manual: `curl http://127.0.0.1:18900/api/ontology/communication` returns channel types + thread modes
7. Manual: `curl http://127.0.0.1:18900/api/ontology/resources` returns model tiers + tools + knowledge sources

---

## Files

| File | Action |
|------|--------|
| `config/ontology/operations.yaml` | **NEW** — Operations domain: standing order tiers, watch types, alert procedures, duty categories |
| `config/ontology/communication.yaml` | **NEW** — Communication domain: channel types, thread modes, message patterns |
| `config/ontology/resources.yaml` | **NEW** — Resources domain: model tiers, tool capabilities, knowledge sources |
| `src/probos/ontology.py` | **MODIFY** — 12 new dataclasses, 3 `_load_*()` methods, 12 query methods, `get_crew_context()` extension |
| `src/probos/api.py` | **MODIFY** — 3 new REST endpoints |
| `tests/test_ontology_ops_comms_resources.py` | **NEW** — 25 tests |
