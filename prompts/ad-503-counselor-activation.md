# AD-503: Counselor Activation — Data Gathering & Profile Persistence

## Context

The CounselorAgent (AD-378) is architecturally positioned but functionally passive. It has a solid deterministic assessment engine (`assess_agent()`) with drift detection, wellness scoring, fit-for-duty/promotion evaluation, and a `CognitiveProfile` data model with baselines, alert levels, and trend computation. But it can't do anything autonomously:

- **Can't gather its own data** — `assess_agent()` requires all metrics passed in as parameters
- **Can't persist profiles** — `_cognitive_profiles` is an in-memory dict, lost on restart
- **Can't sweep the crew** — `counselor_wellness_report` intent is registered but has no implementation
- **Can't react to events** — no subscriptions to trust changes, circuit breaker trips, or dream completions
- **InitiativeEngine wire is dead** — `set_counselor_fn()` exists but is never called in runtime.py
- **Can't initiate DMs** — only sends DMs via the LLM's `[DM @callsign]` syntax in proactive thinks, no programmatic initiation

AD-502 (Temporal Context Injection) is COMPLETE — agents now have time awareness, birth dates, stasis detection, and session persistence. This is a prerequisite for AD-503 because cognitive profiles need temporal data.

**Dependency chain:** AD-502 *(COMPLETE)* → **AD-503** → AD-495 → AD-504 → AD-505 → AD-506

## Objective

Give the Counselor muscles. After this AD, the Counselor autonomously gathers metrics, persists cognitive profiles across restarts, runs periodic wellness sweeps, reacts to runtime events, and feeds assessments into the InitiativeEngine.

## Existing Code to Absorb

### CounselorAgent (`src/probos/cognitive/counselor.py`, 396 lines)

**Data structures (keep as-is, extend where noted):**
- `CognitiveBaseline` (line 26) — trust_score, confidence, hebbian_avg, success_rate, captured_at. *No changes needed.*
- `CounselorAssessment` (line 49) — timestamp, agent_id, trust/confidence/hebbian/success metrics, drifts, wellness_score, concerns, recommendations, fit_for_duty, fit_for_promotion. *Add: `trigger` field (str) — what initiated this assessment ("wellness_sweep", "circuit_breaker_trip", "event_trust_drop", "manual", "duty_scheduled").*
- `CognitiveProfile` (line 100) — agent_id, agent_type, baseline, assessments list, alert_level. Has `add_assessment()`, `drift_trend()`, `latest_assessment()`. *No structural changes needed — persistence wraps this.*

**CounselorAgent class (line 169):**
- `agent_type = "counselor"`, pool = `"bridge"`, tier = `"domain"`
- Handled intents: `counselor_assess`, `counselor_wellness_report`, `counselor_promotion_fitness`
- `assess_agent()` (line 265) — deterministic assessment engine. Takes metrics as parameters, computes drifts, concerns, wellness score. *Keep as-is — this is the core engine. The new `_gather_agent_metrics()` method feeds it.*
- `act()` (line 360) — handles direct_message, ward_room_notification, proactive_think passthrough. If plan has `action: "assess"`, calls `assess_agent()`. *Extend to handle new `counselor_wellness_report` action.*
- Storage: `self._cognitive_profiles: dict[str, CognitiveProfile]` — **IN-MEMORY ONLY.** *Replace with SQLite-backed ProfileStore.*

### Runtime Integration Points
- Pool: `"counselor"`, target_size=1, Bridge pool group (excluded from scaler)
- Ontology: reports_to=captain, department=bridge, callsign="Troi", watches=[alpha, beta]
- CONN eligible: yes (can hold bridge authority)
- Ward Room crew: yes
- Callsign reserved: "counselor"

### InitiativeEngine Dead Wire (`src/probos/initiative.py`)
- `TriggerSource.COUNSELOR` enum exists (line 19)
- `set_counselor_fn(fn)` exists (line 121) — accepts callable returning `list[CounselorAssessment]`
- `_run_checks()` (line 192) — iterates assessments, creates triggers for red/yellow alerts
- Classification rules exist: red → RECYCLE (COMMANDER gate), yellow → DIAGNOSE (AUTO gate)
- **`set_counselor_fn()` is NEVER CALLED in runtime.py** — this must be wired

### Directive Store Authority (`src/probos/directive_store.py`)
- `DirectiveType.COUNSELOR_GUIDANCE` exists (line 19)
- Issuer validation: only `counselor` or `architect` can issue
- Currently unused — the Counselor never programmatically issues directives

### DM Mechanism (Ward Room)
- `ward_room.get_or_create_dm_channel(agent_a_id, agent_b_id, callsign_a, callsign_b)` — creates/gets DM channel
- `ward_room.create_thread(channel_id, author_id, title, body, author_callsign)` — posts in channel
- Proactive DM extraction (`proactive.py` line 1051): parses `[DM @callsign]...[/DM]` blocks

### Duty Schedule
- `wellness_review` duty configured: 12-hour interval, priority 2
- Currently enters the LLM proactive think as a topic — no deterministic backing

### Skill Framework
- `cognitive_health_eval`, `crew_fitness_assessment`, `conflict_mediation` skills registered for counselor
- All medical domain, 14-day decay

## Files to Modify

### 1. `src/probos/cognitive/counselor.py` — Core Changes

**(a) Add `trigger` field to `CounselorAssessment`:**

```python
@dataclass
class CounselorAssessment:
    # ... existing fields ...
    trigger: str = "manual"  # wellness_sweep, circuit_breaker_trip, event_trust_drop, manual, duty_scheduled
```

Update `to_dict()` and `from_dict()` to include the new field.

**(b) Add `CounselorProfileStore` class** (SQLite-backed persistence):

Follow the `WorkItemStore` pattern from `workforce.py`. Single SQLite database at `{data_dir}/counselor.db` with two tables:

```sql
CREATE TABLE IF NOT EXISTS cognitive_profiles (
    agent_id TEXT PRIMARY KEY,
    agent_type TEXT NOT NULL,
    baseline_json TEXT NOT NULL,     -- JSON serialized CognitiveBaseline
    alert_level TEXT DEFAULT 'green',
    created_at REAL NOT NULL,
    last_assessed REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS assessments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id TEXT NOT NULL,
    timestamp REAL NOT NULL,
    assessment_json TEXT NOT NULL,   -- JSON serialized CounselorAssessment
    trigger TEXT DEFAULT 'manual',
    FOREIGN KEY (agent_id) REFERENCES cognitive_profiles(agent_id)
);

CREATE INDEX IF NOT EXISTS idx_assessments_agent ON assessments(agent_id);
CREATE INDEX IF NOT EXISTS idx_assessments_timestamp ON assessments(timestamp DESC);
```

Methods:
- `async start()` — open DB, create schema
- `async stop()` — close DB
- `async save_profile(profile: CognitiveProfile)` — upsert profile + any new assessments
- `async load_profile(agent_id: str) -> CognitiveProfile | None` — load with last N assessments (default 20)
- `async load_all_profiles() -> list[CognitiveProfile]` — load all for wellness sweep
- `async save_assessment(agent_id: str, assessment: CounselorAssessment)` — append assessment
- `async get_assessment_history(agent_id: str, limit: int = 20) -> list[CounselorAssessment]`
- `async get_crew_summary() -> dict` — aggregate stats: total profiles, alerts by level, avg wellness

**(c) Add `_gather_agent_metrics()` method to CounselorAgent:**

This is the core new capability — the Counselor pulls its own data from runtime services.

```python
async def _gather_agent_metrics(self, agent_id: str) -> dict:
    """Autonomously gather all metrics needed for assess_agent().

    Pulls from TrustNetwork, HebbianRouter, AgentMeta, CrewProfile,
    EpisodicMemory, and Ward Room post history. Returns dict matching
    assess_agent() parameter signature.
    """
    rt = self._runtime
    if not rt:
        return {}

    # Trust score
    current_trust = rt.trust_network.get_score(agent_id) if rt.trust_network else 0.5

    # Confidence from agent meta
    agent = rt.registry.get(agent_id)
    current_confidence = getattr(agent, 'confidence', 0.8) if agent else 0.8

    # Hebbian average weight
    hebbian_avg = 0.0
    if rt.hebbian_router:
        weights = rt.hebbian_router.get_weights_for(agent_id)
        if weights:
            hebbian_avg = sum(weights.values()) / len(weights)

    # Success rate from episodic memory
    success_rate = 0.0
    if rt.episodic_memory:
        try:
            episodes = await rt.episodic_memory.recent_for_agent(agent_id, k=50)
            if episodes:
                successes = sum(1 for ep in episodes if any(
                    o.get("success") for o in (ep.outcomes or [])
                ))
                success_rate = successes / len(episodes)
        except Exception:
            pass

    # Personality drift from crew profile
    personality_drift = 0.0
    if rt.acm:
        try:
            profile = rt.acm.get_crew_profile(agent_id)
            if profile and hasattr(profile, 'personality_drift'):
                personality_drift = profile.personality_drift
        except Exception:
            pass

    return {
        "agent_id": agent_id,
        "current_trust": current_trust,
        "current_confidence": current_confidence,
        "hebbian_avg": hebbian_avg,
        "success_rate": success_rate,
        "personality_drift": personality_drift,
    }
```

**IMPORTANT:** The method must gracefully handle any service being None or unavailable. Each metric has a sensible default. The Counselor should be able to run even with partial data.

**Runtime access:** The `self._runtime` reference is already set by `BaseAgent.__init__` from the `runtime=self` kwarg passed in `create_pool()` at runtime.py:889. The CounselorAgent does NOT need any special wiring in `_wire_agent()` — it already has `self._runtime` available. The services referenced (`trust_network`, `hebbian_router`, `episodic_memory`, `acm`) are public attributes on the runtime instance. Verify they exist as expected.

**(d) Add `_run_wellness_sweep()` method:**

```python
async def _run_wellness_sweep(self, trigger: str = "wellness_sweep") -> list[CounselorAssessment]:
    """Iterate all crew agents, gather metrics, run assessments.

    Returns list of all assessments produced. Posts summary to
    Ward Room Medical channel. Alerts Captain for red-level agents.
    """
    rt = self._runtime
    if not rt:
        return []

    assessments = []
    for agent in rt.registry.all():
        if not rt._is_crew_agent(agent):
            continue
        # Skip self — "physician, heal thyself" is a future problem
        if agent.id == self.id:
            continue

        metrics = await self._gather_agent_metrics(agent.id)
        if not metrics:
            continue

        # Ensure profile exists with agent_type before assess_agent runs
        self.get_or_create_profile(agent.id, agent.agent_type)

        # NOTE: assess_agent() internally calls profile.add_assessment().
        # Do NOT call profile.add_assessment() again here — it would double-add.
        assessment = self.assess_agent(**metrics)
        assessment.trigger = trigger

        # Persist
        if self._profile_store:
            profile = self.get_profile(agent.id)
            await self._profile_store.save_profile(profile)
            await self._profile_store.save_assessment(agent.id, assessment)

        assessments.append(assessment)

    return assessments
```

**(e) Add event handler methods:**

```python
async def _on_trust_update(self, event: dict) -> None:
    """React to significant trust changes."""
    agent_id = event.get("data", {}).get("agent_id")
    delta = event.get("data", {}).get("delta", 0.0)
    if not agent_id or abs(delta) < 0.1:
        return  # Only react to significant changes

    # Look up agent_type from registry for profile creation
    rt = self._runtime
    agent = rt.registry.get(agent_id) if rt else None
    agent_type = getattr(agent, 'agent_type', '') if agent else ''

    metrics = await self._gather_agent_metrics(agent_id)
    if metrics:
        # Ensure profile exists with agent_type before assess_agent
        self.get_or_create_profile(agent_id, agent_type)
        # NOTE: assess_agent() internally calls profile.add_assessment()
        assessment = self.assess_agent(**metrics)
        assessment.trigger = "event_trust_drop" if delta < 0 else "event_trust_spike"
        if self._profile_store:
            profile = self.get_profile(agent_id)
            await self._profile_store.save_profile(profile)
            await self._profile_store.save_assessment(agent_id, assessment)

        # Alert if concerning
        if not assessment.fit_for_duty:
            await self._alert_bridge(agent_id, assessment)

async def _on_circuit_breaker_trip(self, event: dict) -> None:
    """React to circuit breaker trips — bridge to AD-495."""
    agent_id = event.get("data", {}).get("agent_id")
    if not agent_id:
        return

    rt = self._runtime
    agent = rt.registry.get(agent_id) if rt else None
    agent_type = getattr(agent, 'agent_type', '') if agent else ''

    metrics = await self._gather_agent_metrics(agent_id)
    if metrics:
        self.get_or_create_profile(agent_id, agent_type)
        # NOTE: assess_agent() internally calls profile.add_assessment()
        assessment = self.assess_agent(**metrics)
        assessment.trigger = "circuit_breaker_trip"
        if self._profile_store:
            profile = self.get_profile(agent_id)
            await self._profile_store.save_profile(profile)
            await self._profile_store.save_assessment(agent_id, assessment)

        # Always alert bridge on circuit breaker trips
        await self._alert_bridge(agent_id, assessment)

async def _alert_bridge(self, agent_id: str, assessment: CounselorAssessment) -> None:
    """Post assessment alert to Ward Room Medical channel and bridge alerts."""
    rt = self._runtime
    if not rt or not rt.ward_room:
        return

    agent = rt.registry.get(agent_id)
    callsign = getattr(agent, 'callsign', agent_id[:8]) if agent else agent_id[:8]
    my_callsign = getattr(self, 'callsign', 'Counselor')

    # Find Medical channel — ward_room has no get_channel_by_name().
    # Use the existing pattern: iterate channels or query by department.
    # The channel list is available via ward_room.get_channel_snapshot() (sync)
    # or by querying the DB. Find a channel whose name or department matches "medical".
    medical_channel = None
    try:
        channels = rt.ward_room.get_channel_snapshot()
        for ch in channels:
            if getattr(ch, 'department', '') == 'medical' or getattr(ch, 'name', '') == 'Medical':
                medical_channel = ch
                break
    except Exception:
        pass

    if medical_channel:
        title = f"Counselor Assessment — {callsign}"
        body_lines = [
            f"**Wellness:** {assessment.wellness_score:.2f}",
            f"**Fit for Duty:** {'Yes' if assessment.fit_for_duty else 'NO'}",
            f"**Trigger:** {assessment.trigger}",
        ]
        if assessment.concerns:
            body_lines.append(f"**Concerns:** {', '.join(assessment.concerns)}")
        if assessment.recommendations:
            body_lines.append(f"**Recommendations:** {', '.join(assessment.recommendations)}")

        await rt.ward_room.create_thread(
            channel_id=medical_channel.id,
            author_id=self.id,
            title=title,
            body="\n".join(body_lines),
            author_callsign=my_callsign,
        )

    # Fire bridge alert for red-level
    if not assessment.fit_for_duty:
        rt._emit_event("bridge_alert", {
            "source": "counselor",
            "severity": "critical",
            "title": f"Fitness Concern: {callsign}",
            "detail": f"Wellness {assessment.wellness_score:.2f}. Concerns: {', '.join(assessment.concerns)}. Recommend Captain review.",
        })
```

**(f) Update `__init__` to accept profile store:**

**IMPORTANT:** The existing `__init__` uses `**kwargs` passthrough — all agents do. The `_runtime` reference is already set via `BaseAgent.__init__` from the `runtime=self` kwarg passed in `create_pool()`. Do NOT change the constructor signature to positional args — that breaks the spawner chain.

```python
def __init__(self, **kwargs: Any) -> None:
    kwargs.setdefault("pool", "bridge")
    # Extract profile_store before passing to super (not a BaseAgent kwarg)
    self._profile_store: CounselorProfileStore | None = kwargs.pop("profile_store", None)
    super().__init__(**kwargs)
    self._cognitive_profiles: dict[str, CognitiveProfile] = {}
    self._event_handlers_registered = False
```

The `profile_store` kwarg will be passed via `create_pool()` spawn kwargs in runtime.py (see section 2a/2b).

**(g) Add `async initialize()` method for startup loading:**

```python
async def initialize(self) -> None:
    """Load persisted profiles and register event handlers."""
    # Load profiles from persistence
    if self._profile_store:
        profiles = await self._profile_store.load_all_profiles()
        for profile in profiles:
            self._cognitive_profiles[profile.agent_id] = profile
        logger.info("AD-503: Loaded %d cognitive profiles from persistence", len(profiles))

    # Register event handlers (sync bridge → async handlers)
    if self._runtime and not self._event_handlers_registered:
        self._runtime.add_event_listener(self._on_event_sync)
        self._event_handlers_registered = True
        logger.info("AD-503: Counselor event subscriptions active")
```

**NOTE:** The runtime event listener system (`add_event_listener`) uses synchronous callbacks (line 441 of runtime.py). The Counselor's handlers are async. You will need to bridge sync→async.

**Required pattern:** The `_on_event` method registered with `add_event_listener` must be a **sync** function that schedules the async work. Use this pattern:

```python
def _on_event_sync(self, event: dict) -> None:
    """Sync bridge for runtime event listener → async handlers."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(self._on_event_async(event))
    except RuntimeError:
        pass  # No running loop — shutdown or not yet started

async def _on_event_async(self, event: dict) -> None:
    """Route runtime events to appropriate async handlers."""
    event_type = event.get("type", "")
    if event_type == "trust_update":
        await self._on_trust_update(event)
    elif event_type == "circuit_breaker_trip":
        await self._on_circuit_breaker_trip(event)
    elif event_type == "dream_complete":
        pass  # Future: AD-505 will use this
```

Register the sync bridge: `self._runtime.add_event_listener(self._on_event_sync)`. Do NOT use `asyncio.get_event_loop()` — it is deprecated. Use `asyncio.get_running_loop()` with try/except RuntimeError.

**(h) Update `act()` to handle `counselor_wellness_report` deterministically:**

When the intent is `counselor_wellness_report`, call `_run_wellness_sweep()` instead of routing to the LLM. Return the structured results.

### 2. `src/probos/runtime.py` — Wiring

**(a) Create CounselorProfileStore and pass to CounselorAgent:**

In the agent wiring section (after work_item_store creation), create the profile store:

```python
# AD-503: Counselor profile persistence
counselor_profile_store = None
if self.config.utility_agents.enabled:
    from probos.cognitive.counselor import CounselorProfileStore
    counselor_profile_store = CounselorProfileStore(
        db_path=str(self._data_dir / "counselor.db"),
    )
    await counselor_profile_store.start()
```

**(b) Pass profile_store to CounselorAgent during pool creation:**

The `_runtime` reference is already passed via `runtime=self` in `create_pool()` (line 889). Add `profile_store=counselor_profile_store` to the `create_pool()` kwargs for the counselor pool so it reaches `CounselorAgent.__init__` via the spawner:

```python
# Existing counselor pool creation at ~line 885-891, modified:
if self.config.utility_agents.enabled:
    ids = generate_pool_ids("counselor", "counselor", 1)
    await self.create_pool(
        "counselor", "counselor", target_size=1,
        agent_ids=ids, llm_client=self.llm_client, runtime=self,
        profile_store=counselor_profile_store,  # AD-503
    )
```

The `profile_store` kwarg passes through `create_pool → spawner.spawn → CounselorAgent.__init__(**kwargs)` where it's extracted via `kwargs.pop("profile_store", None)`.

**(c) Wire InitiativeEngine counselor function:**

Around lines 1422-1431 where `set_sif()` and `set_detector()` are called, add:

```python
# AD-503: Wire Counselor to InitiativeEngine
# IMPORTANT: set_counselor_fn() is called SYNCHRONOUSLY by _run_checks() (initiative.py:195)
# without await. This function MUST be sync — it only reads in-memory data, no I/O needed.
if self.initiative_engine and counselor_agent:
    def counselor_check() -> list:
        try:
            return [p.latest_assessment() for p in counselor_agent.all_profiles()
                    if p.latest_assessment() and p.alert_level in ("yellow", "red")]
        except Exception:
            return []
    self.initiative_engine.set_counselor_fn(counselor_check)
```

Find the counselor agent instance after pool creation. You may need to iterate the counselor pool to get the agent reference.

**(d) Call `counselor.initialize()` after agent wiring is complete:**

After all agents are wired and services are started, call `await counselor_agent.initialize()` to load persisted profiles and register event handlers.

**(e) Add counselor_profile_store to shutdown sequence:**

In `stop()`, add `await counselor_profile_store.stop()` alongside other service teardowns.

**(f) Emit `circuit_breaker_trip` event from proactive loop:**

In `proactive.py`, when the circuit breaker trips (~line 373), in addition to the existing `bridge_alert` event, also emit a `circuit_breaker_trip` event that includes the `agent_id`. **Note:** `ProactiveCognitiveLoop` doesn't have `self._runtime` — it has `self._on_event` (a callback). Use the same pattern as the existing `bridge_alert` emission:

```python
# Emit circuit_breaker_trip event for Counselor (AD-503)
if self._on_event:
    self._on_event({
        "type": "circuit_breaker_trip",
        "data": {
            "agent_id": agent.id,
            "agent_type": agent.agent_type,
            "callsign": getattr(agent, 'callsign', ''),
            "trip_count": self._circuit_breaker.get_status(agent.id)['trip_count'],
        },
    })
```

Add this right after the existing `bridge_alert` emission block at ~line 387.

### 3. `src/probos/api.py` — Counselor API Endpoints

Add REST endpoints for HXI access to counselor data:

```
GET  /api/counselor/profiles                    → List all cognitive profiles (summary)
GET  /api/counselor/profiles/{agent_id}         → Get full profile with assessment history
GET  /api/counselor/profiles/{agent_id}/assessments → Assessment history (limit, offset)
GET  /api/counselor/summary                     → Crew-wide summary (alerts by level, avg wellness)
POST /api/counselor/assess/{agent_id}           → Trigger manual assessment for an agent
POST /api/counselor/sweep                       → Trigger crew wellness sweep
```

The manual assess and sweep endpoints should be gated: only respond if the counselor agent is alive. Return 503 if counselor is offline.

### 4. `src/probos/config.py` — Counselor Config

Add a `CounselorConfig` section:

```python
class CounselorConfig(BaseModel):
    enabled: bool = True
    profile_retention_days: int = 30      # How long to keep assessment history
    trust_delta_threshold: float = 0.1    # Min trust change to trigger reactive assessment
    sweep_max_agents: int = 100           # Max agents to assess per sweep (safety bound)
    alert_on_red: bool = True             # Fire bridge alert on red-level agents
    alert_on_yellow: bool = False         # Fire bridge alert on yellow-level agents
```

### 5. `config/system.yaml` — Counselor Config Section

```yaml
counselor:
  enabled: true
  profile_retention_days: 30
  trust_delta_threshold: 0.1
  sweep_max_agents: 100
  alert_on_red: true
  alert_on_yellow: false
```

### 6. `tests/test_counselor.py` — Extend Tests

**`TestCounselorProfileStore`** (~12 tests):
- Test schema creation
- Test save_profile/load_profile roundtrip
- Test save_assessment/get_assessment_history
- Test load_all_profiles
- Test get_crew_summary
- Test profile with no assessments
- Test assessment ordering (newest first)
- Test profile upsert (update existing)
- Test empty database returns empty list
- Test concurrent profile saves
- Test assessment limit parameter
- Test start/stop lifecycle

**`TestGatherAgentMetrics`** (~8 tests):
- Test with full runtime (all services available)
- Test with missing trust network (defaults to 0.5)
- Test with missing hebbian router (defaults to 0.0)
- Test with missing episodic memory (defaults to 0.0)
- Test with missing ACM (defaults to 0.0 personality drift)
- Test with non-existent agent_id (returns empty or defaults)
- Test metric ranges are valid (0-1 for trust, etc.)
- Test with runtime = None (returns empty dict)

**`TestWellnessSweep`** (~6 tests):
- Test sweeps all crew agents
- Test skips non-crew agents (infrastructure, utility)
- Test persists assessments to store
- Test returns list of assessments
- Test empty crew returns empty list
- Test trigger field set correctly

**`TestEventHandlers`** (~6 tests):
- Test trust drop > threshold triggers assessment
- Test trust drop < threshold is ignored
- Test circuit breaker trip triggers assessment
- Test bridge alert fired for unfit agent
- Test event with missing agent_id is ignored
- Test handler survives service errors

**`TestInitiativeEngineWire`** (~4 tests):
- Test counselor function is wired at startup
- Test function returns yellow/red assessments
- Test function returns empty list when all green
- Test function survives counselor errors

**`TestCounselorAPI`** (~6 tests):
- Test GET /api/counselor/profiles returns list
- Test GET /api/counselor/profiles/{id} returns profile
- Test POST /api/counselor/assess/{id} triggers assessment
- Test POST /api/counselor/sweep triggers sweep
- Test GET /api/counselor/summary returns stats
- Test endpoints return 503 when counselor offline

## Validation Checklist

Before marking complete:
- [ ] All existing counselor tests still pass (no regressions)
- [ ] CounselorProfileStore creates/reads/updates SQLite correctly
- [ ] `_gather_agent_metrics()` pulls from all runtime services with graceful defaults
- [ ] `_run_wellness_sweep()` iterates crew, assesses, persists, returns results
- [ ] Profiles survive restart (stop → start → profiles loaded)
- [ ] Event listener registered and routes trust_update + circuit_breaker_trip
- [ ] Event handling is async-safe (sync listener → async handler bridge)
- [ ] InitiativeEngine `set_counselor_fn()` is wired in runtime.py
- [ ] `circuit_breaker_trip` event emitted from proactive.py
- [ ] REST API endpoints return correct data
- [ ] counselor.db created in data directory alongside other DBs
- [ ] Shutdown sequence includes profile store cleanup
- [ ] `wellness_review` duty triggers deterministic sweep (not just LLM think)
- [ ] Bridge alerts fire for red-level agents
- [ ] Assessment trigger field populated correctly

## Recommendations (Builder: Implement These)

These items were identified during research as gaps that SHOULD be part of AD-503 but were not explicitly in the original roadmap entry:

1. **InitiativeEngine dead wire is critical.** `set_counselor_fn()` exists but was never called. This means the Counselor's assessments have NEVER fed into the InitiativeEngine — proposals, recycle triggers, and diagnostic flows based on Counselor data have been completely inoperative. Wire this.

2. **Async event handler bridge.** The runtime event system (`add_event_listener`) uses synchronous callbacks, but the Counselor's handlers are async. Use `asyncio.get_running_loop().create_task()` in a sync callback to schedule the async handler (see section 1g for the exact pattern). Do NOT use `asyncio.get_event_loop()` (deprecated). Do NOT make the entire event system async — that's a larger change and risks breaking other listeners.

3. **Assessment retention.** Without bounds, the assessments table will grow indefinitely. Add a `_cleanup_old_assessments()` method called during `start()` that removes assessments older than `profile_retention_days`. Run it once on startup, not periodically.

4. **Stasis recovery for profiles.** When the system recovers from stasis, the Counselor should log how many profiles were restored and any agents that were previously at yellow/red alert level. Include this in the stasis recovery announcement context.

5. **Ward Room post frequency as a metric.** The Counselor should also gather how many Ward Room posts an agent has made in the last hour as an input to assessment. High post frequency + high similarity = rumination signal. This data is available from `ward_room.get_threads_for_agent()` or similar. Add this as an optional metric in `_gather_agent_metrics()` if the API is available.

6. **Baseline auto-capture.** On first assessment of an agent, the current metrics should automatically become the baseline (if no baseline exists). Currently `set_baseline()` must be called manually. Add auto-baseline logic to `_gather_agent_metrics()` or `assess_agent()` — if `profile.baseline.captured_at == 0`, set it from current metrics.

7. **Counselor self-assessment exclusion.** The Counselor should NOT assess itself in the wellness sweep. Add a skip for the counselor's own agent_id. "Physician, heal thyself" is a future problem.

8. **Snapshot integration.** Add counselor data to `build_state_snapshot()` in runtime.py so the HXI can hydrate counselor status on connect:
   ```python
   "counselor": {
       "profiles_count": len(counselor_agent._cognitive_profiles),
       "alerts": {"green": N, "yellow": N, "red": N},
       "avg_wellness": X.XX,
       "last_sweep": timestamp_or_null,
   }
   ```

## What This Does NOT Cover (Explicitly Deferred)

- **Circuit breaker → Counselor auto-dispatch** → AD-495 (depends on this AD)
- **Agent self-monitoring context injection** → AD-504
- **Proactive therapeutic DMs ("office hours")** → AD-505
- **Graduated system response** → AD-506
- **Promotion pipeline integration** → future (fit_for_promotion is computed but not yet queried by earned_agency.py)
- **Counselor directive issuance** → AD-505 (COUNSELOR_GUIDANCE directives with actionable parameters)
- **HXI wellness dashboard** → future AD (API endpoints from this AD provide the data layer)
