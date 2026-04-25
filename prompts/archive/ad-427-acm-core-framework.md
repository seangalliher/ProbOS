# AD-427: Agent Capital Management (ACM) — Core Framework

**Goal:** Consolidate ProbOS's piecemeal HCM-equivalent capabilities into an integrated agent lifecycle framework. ACM wraps existing subsystems (TrustNetwork, EarnedAgency, CrewProfile, SkillFramework, DutyScheduleTracker) with lifecycle management and a unified profile — it does NOT replace them. "ACM is the HR department — it doesn't do the work, it manages the people who do the work."

**Prerequisites (all COMPLETE):** AD-398 (three-tier classification), AD-357 (Earned Agency), AD-419 (Duty Schedules), AD-428 (Skill Framework), AD-376 (CrewProfile/CallsignRegistry).

**Boundary:** Advanced features (workforce analytics, structured evaluations, succession planning, mentor assignment, career pathing) are commercial. This AD provides the core lifecycle and consolidated profile.

---

## Step 1: Lifecycle State Machine

Create `src/probos/acm.py` — the Agent Capital Management service.

### LifecycleState Enum

```python
from enum import Enum

class LifecycleState(str, Enum):
    """Agent lifecycle states — HR status, not operational state."""
    REGISTERED = "registered"       # Created, not yet onboarded
    PROBATIONARY = "probationary"   # Onboarded, building trust
    ACTIVE = "active"               # Full crew member
    SUSPENDED = "suspended"         # Temporarily removed from duty (Captain order)
    DECOMMISSIONED = "decommissioned"  # Permanently retired, read-only archive
```

Note: This is distinct from `AgentState` (SPAWNING/ACTIVE/DEGRADED/RECYCLING) which tracks operational runtime state. `LifecycleState` tracks HR/administrative status.

### LifecycleTransition Dataclass

```python
@dataclass
class LifecycleTransition:
    """Record of a lifecycle state change."""
    agent_id: str
    from_state: str         # LifecycleState value (or "" for initial)
    to_state: str           # LifecycleState value
    reason: str             # Why the transition happened
    initiated_by: str       # "system", "captain", agent_id
    timestamp: float        # time.time()
```

### SQLite Schema

In the ACM service's `start()`, create/open a database at `{data_dir}/acm.db`:

```sql
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
```

---

## Step 2: AgentCapitalService

The core ACM service — Ship's Computer infrastructure (no identity, no personality).

```python
class AgentCapitalService:
    """Agent Capital Management — consolidated lifecycle and profile service.

    Infrastructure service (Ship's Computer). Wraps existing subsystems
    into a unified agent management layer.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self._data_dir = Path(data_dir)
        self._db: aiosqlite.Connection | None = None

    async def start(self) -> None:
        """Initialize ACM database."""
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self._data_dir / "acm.db"))
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def stop(self) -> None:
        """Close ACM database."""
        if self._db:
            await self._db.close()
            self._db = None
```

### Core Methods

#### `get_lifecycle_state(agent_id) -> LifecycleState`

```python
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
```

#### `transition(agent_id, to_state, reason, initiated_by) -> LifecycleTransition`

```python
async def transition(
    self, agent_id: str, to_state: LifecycleState,
    reason: str = "", initiated_by: str = "system",
) -> LifecycleTransition:
    """Transition an agent to a new lifecycle state.

    Validates transition is legal, records the change, returns the transition record.
    """
```

**Legal transitions (enforce these):**
- `REGISTERED → PROBATIONARY` (onboarding)
- `PROBATIONARY → ACTIVE` (trust threshold met)
- `ACTIVE → SUSPENDED` (Captain order)
- `SUSPENDED → ACTIVE` (Captain reinstatement)
- `ACTIVE → DECOMMISSIONED` (offboarding)
- `SUSPENDED → DECOMMISSIONED` (offboarding from suspension)
- `PROBATIONARY → DECOMMISSIONED` (failed probation)

Raise `ValueError` for illegal transitions.

Record the transition in both tables:
1. Update `lifecycle` table (state, state_since, set onboarded_at/decommissioned_at timestamps as appropriate)
2. Insert into `lifecycle_transitions` (audit trail)

Return the `LifecycleTransition` dataclass.

#### `get_transition_history(agent_id) -> list[LifecycleTransition]`

Return all transitions for an agent, ordered by timestamp ascending.

#### `onboard(agent_id, agent_type, pool, department, initiated_by) -> LifecycleTransition`

High-level onboarding flow:

```python
async def onboard(
    self, agent_id: str, agent_type: str, pool: str, department: str,
    initiated_by: str = "system",
) -> LifecycleTransition:
    """Onboard an agent — register and set to probationary."""
    now = time.time()
    # Ensure lifecycle record exists
    await self._db.execute(
        "INSERT OR IGNORE INTO lifecycle (agent_id, state, state_since) VALUES (?, ?, ?)",
        (agent_id, LifecycleState.REGISTERED.value, now),
    )
    await self._db.commit()
    # Transition to probationary
    return await self.transition(
        agent_id, LifecycleState.PROBATIONARY,
        reason=f"Onboarded as {agent_type} in {department}",
        initiated_by=initiated_by,
    )
```

#### `decommission(agent_id, reason, initiated_by) -> LifecycleTransition`

```python
async def decommission(
    self, agent_id: str, reason: str = "Decommissioned by Captain",
    initiated_by: str = "captain",
) -> LifecycleTransition:
    """Decommission an agent — set to decommissioned state."""
    return await self.transition(
        agent_id, LifecycleState.DECOMMISSIONED,
        reason=reason, initiated_by=initiated_by,
    )
```

#### `get_consolidated_profile(agent_id, runtime) -> dict`

This is the key consolidation method. Pulls data from multiple subsystems into one view:

```python
async def get_consolidated_profile(
    self, agent_id: str, runtime: Any,
) -> dict[str, Any]:
    """Consolidated profile — single view of an agent across all subsystems."""
    profile: dict[str, Any] = {"agent_id": agent_id}

    # 1. Lifecycle state (this service)
    state = await self.get_lifecycle_state(agent_id)
    profile["lifecycle_state"] = state.value
    # Get timestamps from lifecycle table
    if self._db:
        async with self._db.execute(
            "SELECT state_since, onboarded_at, decommissioned_at FROM lifecycle WHERE agent_id = ?",
            (agent_id,),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                profile["state_since"] = row[0]
                profile["onboarded_at"] = row[1]
                profile["decommissioned_at"] = row[2]

    # 2. Crew profile (AD-376) — identity, personality, rank
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

    # 3. Trust (Phase 17) — current score
    if hasattr(runtime, 'trust_network'):
        profile["trust"] = round(runtime.trust_network.get_score(agent_id), 4)

    # 4. Earned Agency (AD-357) — current agency level
    agent = runtime.agent_registry.get(agent_id) if hasattr(runtime, 'agent_registry') else None
    if agent and hasattr(agent, 'rank'):
        from probos.earned_agency import agency_from_rank
        profile["agency_level"] = agency_from_rank(agent.rank).value

    # 5. Skills (AD-428) — skill profile summary
    if hasattr(runtime, 'skill_service') and runtime.skill_service:
        try:
            skill_profile = await runtime.skill_service.get_profile(agent_id)
            profile["skill_count"] = skill_profile.total_skills
            profile["avg_proficiency"] = skill_profile.avg_proficiency
        except Exception:
            pass

    # 6. Episodic memory count (BF-033)
    if hasattr(runtime, 'episodic_memory') and runtime.episodic_memory:
        if hasattr(runtime.episodic_memory, 'count_for_agent'):
            profile["episode_count"] = await runtime.episodic_memory.count_for_agent(agent_id)

    return profile
```

The key principle: read from existing subsystems, don't duplicate data. ACM is the lens, not the store.

---

## Step 3: Runtime Integration

### 3a. Instantiate ACM in `runtime.py`

In `ProbOSRuntime.__init__()`, add:

```python
self.acm: AgentCapitalService | None = None
```

In `start()`, after the Skill Framework is started (`skill_service.start()`), start ACM:

```python
# AD-427: Agent Capital Management
from probos.acm import AgentCapitalService
self.acm = AgentCapitalService(data_dir=data_dir)
await self.acm.start()
```

In `stop()`, before other services are torn down (but after the shutdown announcement):

```python
if self.acm:
    await self.acm.stop()
    self.acm = None
```

### 3b. Onboard agents during wiring

In `_wire_agent()`, after the trust record is created (`self.trust_network.get_or_create(agent.id)`) and the agent_state event is emitted, add ACM onboarding for crew agents:

```python
# AD-427: ACM onboarding for crew agents
if self.acm and self._is_crew_agent(agent):
    try:
        from probos.cognitive.standing_orders import _AGENT_DEPARTMENTS
        department = _AGENT_DEPARTMENTS.get(agent.agent_type, "operations")
        await self.acm.onboard(
            agent_id=agent.id,
            agent_type=agent.agent_type,
            pool=agent.pool,
            department=department,
        )
    except Exception as e:
        logger.debug("ACM onboard skipped for %s: %s", agent.id, e)
```

Note: Use `try/except` and `logger.debug` because on subsequent boots the agent will already be onboarded — the `onboard()` will fail on the transition since they're already PROBATIONARY+. The `INSERT OR IGNORE` handles the lifecycle record, but the transition from REGISTERED→PROBATIONARY will raise ValueError if they're already past REGISTERED. This is expected — on warm boot, agents are already in the system. Only truly new agents will successfully onboard.

**Alternative approach if you prefer:** Check `get_lifecycle_state()` first and only call `onboard()` if state is REGISTERED (or no record exists). Either approach works — pick whichever feels cleaner.

---

## Step 4: REST API Endpoints

Add to `api.py`, after the existing skill framework endpoints:

### `GET /api/acm/agents/{agent_id}/profile`

Consolidated profile view:

```python
@app.get("/api/acm/agents/{agent_id}/profile")
async def get_acm_profile(agent_id: str) -> dict[str, Any]:
    """AD-427: Consolidated agent profile from ACM."""
    if not runtime.acm:
        return {"error": "ACM not available"}
    return await runtime.acm.get_consolidated_profile(agent_id, runtime)
```

### `GET /api/acm/agents/{agent_id}/lifecycle`

Lifecycle state + transition history:

```python
@app.get("/api/acm/agents/{agent_id}/lifecycle")
async def get_acm_lifecycle(agent_id: str) -> dict[str, Any]:
    """AD-427: Agent lifecycle state and transition history."""
    if not runtime.acm:
        return {"error": "ACM not available"}
    state = await runtime.acm.get_lifecycle_state(agent_id)
    history = await runtime.acm.get_transition_history(agent_id)
    return {
        "agent_id": agent_id,
        "current_state": state.value,
        "transitions": [
            {
                "from_state": t.from_state,
                "to_state": t.to_state,
                "reason": t.reason,
                "initiated_by": t.initiated_by,
                "timestamp": t.timestamp,
            }
            for t in history
        ],
    }
```

### `POST /api/acm/agents/{agent_id}/decommission`

```python
@app.post("/api/acm/agents/{agent_id}/decommission")
async def decommission_agent(agent_id: str, req: dict) -> dict[str, Any]:
    """AD-427: Decommission an agent."""
    if not runtime.acm:
        return {"error": "ACM not available"}
    reason = req.get("reason", "Decommissioned by Captain")
    try:
        t = await runtime.acm.decommission(agent_id, reason=reason, initiated_by="captain")
        return {"status": "decommissioned", "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        }}
    except ValueError as e:
        return {"error": str(e)}
```

### `POST /api/acm/agents/{agent_id}/suspend`

```python
@app.post("/api/acm/agents/{agent_id}/suspend")
async def suspend_agent(agent_id: str, req: dict) -> dict[str, Any]:
    """AD-427: Suspend an agent (Captain order)."""
    if not runtime.acm:
        return {"error": "ACM not available"}
    reason = req.get("reason", "Suspended by Captain")
    try:
        t = await runtime.acm.transition(
            agent_id, LifecycleState.SUSPENDED,
            reason=reason, initiated_by="captain",
        )
        return {"status": "suspended", "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        }}
    except ValueError as e:
        return {"error": str(e)}
```

### `POST /api/acm/agents/{agent_id}/reinstate`

```python
@app.post("/api/acm/agents/{agent_id}/reinstate")
async def reinstate_agent(agent_id: str, req: dict) -> dict[str, Any]:
    """AD-427: Reinstate a suspended agent."""
    if not runtime.acm:
        return {"error": "ACM not available"}
    reason = req.get("reason", "Reinstated by Captain")
    try:
        t = await runtime.acm.transition(
            agent_id, LifecycleState.ACTIVE,
            reason=reason, initiated_by="captain",
        )
        return {"status": "active", "transition": {
            "from_state": t.from_state, "to_state": t.to_state,
            "reason": t.reason, "timestamp": t.timestamp,
        }}
    except ValueError as e:
        return {"error": str(e)}
```

---

## Tests

Create `tests/test_acm.py`:

### Lifecycle State Machine Tests

```python
class TestLifecycleStateMachine:
    """AD-427: Agent lifecycle transitions."""

    async def test_initial_state_is_registered(self):
        """New agent starts as REGISTERED."""
        # get_lifecycle_state for unknown agent returns REGISTERED

    async def test_onboard_transitions_to_probationary(self):
        """onboard() creates record and transitions REGISTERED → PROBATIONARY."""

    async def test_probationary_to_active(self):
        """transition() allows PROBATIONARY → ACTIVE."""

    async def test_active_to_suspended(self):
        """transition() allows ACTIVE → SUSPENDED (Captain order)."""

    async def test_suspended_to_active(self):
        """transition() allows SUSPENDED → ACTIVE (reinstatement)."""

    async def test_active_to_decommissioned(self):
        """decommission() transitions ACTIVE → DECOMMISSIONED."""

    async def test_illegal_transition_raises(self):
        """Illegal transitions (e.g., REGISTERED → ACTIVE) raise ValueError."""

    async def test_decommissioned_is_terminal(self):
        """Cannot transition out of DECOMMISSIONED."""

    async def test_transition_history_recorded(self):
        """All transitions are recorded in audit trail."""

    async def test_transition_history_ordered_by_timestamp(self):
        """get_transition_history() returns transitions in chronological order."""
```

### Consolidated Profile Tests

```python
class TestConsolidatedProfile:
    """AD-427: Consolidated profile view."""

    async def test_profile_includes_lifecycle_state(self):
        """Consolidated profile contains lifecycle_state field."""

    async def test_profile_includes_trust(self):
        """Consolidated profile contains trust from TrustNetwork."""

    async def test_profile_includes_skills(self):
        """Consolidated profile contains skill_count and avg_proficiency."""

    async def test_profile_includes_episode_count(self):
        """Consolidated profile contains episode_count from EpisodicMemory."""

    async def test_profile_graceful_when_subsystems_unavailable(self):
        """Profile returns partial data when some subsystems are missing."""
```

### Onboarding Integration Tests

```python
class TestOnboardingIntegration:
    """AD-427: Onboarding during agent wiring."""

    async def test_crew_agent_onboarded_during_wiring(self):
        """Crew agents get onboarded (PROBATIONARY) during _wire_agent()."""

    async def test_non_crew_agent_not_onboarded(self):
        """Infrastructure/utility agents skip ACM onboarding."""

    async def test_warm_boot_does_not_duplicate_onboarding(self):
        """Second boot doesn't create duplicate lifecycle records."""
```

### API Endpoint Tests

```python
class TestACMEndpoints:
    """AD-427: ACM REST API."""

    async def test_get_profile_endpoint(self):
        """GET /api/acm/agents/{id}/profile returns consolidated profile."""

    async def test_get_lifecycle_endpoint(self):
        """GET /api/acm/agents/{id}/lifecycle returns state + history."""

    async def test_decommission_endpoint(self):
        """POST /api/acm/agents/{id}/decommission transitions to DECOMMISSIONED."""

    async def test_suspend_endpoint(self):
        """POST /api/acm/agents/{id}/suspend transitions to SUSPENDED."""

    async def test_reinstate_endpoint(self):
        """POST /api/acm/agents/{id}/reinstate transitions SUSPENDED → ACTIVE."""

    async def test_illegal_transition_returns_error(self):
        """Illegal transitions return error dict, not crash."""
```

**Target: ~22 tests.**

---

## Files Modified

| File | Change |
|------|--------|
| `src/probos/acm.py` | **NEW** — LifecycleState, LifecycleTransition, AgentCapitalService |
| `src/probos/runtime.py` | ACM instantiation in `__init__`/`start()`/`stop()`, onboarding in `_wire_agent()` |
| `src/probos/api.py` | 5 new endpoints under `/api/acm/` |
| `tests/test_acm.py` | **NEW** — ~22 tests |

## Out of Scope (Commercial / Future)

- Ward Room introduction/farewell posts (onboarding/offboarding awareness)
- Knowledge preservation during offboarding (episodic → KnowledgeStore promotion)
- Access/permission revocation during decommission
- Duty reassignment during decommission
- Competency Registry domain (delivered by AD-428 Skill Framework)
- Probationary → Active auto-promotion based on trust threshold (future — needs trust monitoring hook)
- Advanced onboarding workflows (mentor assignment, milestones, templated tracks)
- Structured evaluations, succession planning, career pathing
- Workforce analytics, department capability heatmaps
