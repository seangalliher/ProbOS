# AD-290: Medical Team Pool + Codebase Knowledge Service

## Objective

Create a dedicated `medical` pool with five specialized agents that monitor, diagnose, and remediate ProbOS health issues, plus a shared Codebase Knowledge Service that gives any agent structural self-awareness of ProbOS's own source code. The Medical Team operates as an internal health service — the Vitals Monitor watches for problems, the Diagnostician identifies root causes, the Surgeon takes corrective action, the Pharmacist tunes configuration, and the Pathologist analyzes failures for future learning. The Codebase Knowledge Service acts as a library — any agent with a library card (the `codebase_knowledge` skill) can query the architecture.

## Architecture

```
CodebaseIndex (runtime service, built at startup)
    └→ codebase_knowledge skill (available to any CognitiveAgent)

Vitals Monitor (always on) → Diagnostician (on alert or schedule)
                                ├→ Surgeon (acute remediation)
                                ├→ Pharmacist (chronic tuning)
                                └→ Pathologist (post-mortem analysis, uses codebase_knowledge)
```

- The Vitals Monitor is the only agent that runs continuously (HeartbeatAgent subclass)
- All other agents activate on demand via intent bus messages
- The pool is created at boot with `target_size=5` and deterministic agent IDs
- The CodebaseIndex is a runtime-level service, not an agent — built once at startup, read-only

## Files to Create

### `src/probos/cognitive/codebase_index.py`

**Class:** `CodebaseIndex`

A runtime-level service (not an agent) that builds and maintains a structured map of ProbOS's own source code. Built once at startup, cached in memory, read-only during a session.

**Constructor:**
```python
def __init__(self, source_root: Path):
    self._source_root = source_root
    self._file_tree: dict[str, dict] = {}
    self._agent_map: list[dict] = []
    self._layer_map: dict[str, list[str]] = {}
    self._config_schema: dict[str, Any] = {}
    self._built = False
```

**Public methods:**

- `build() -> None` — Scan `source_root` and populate all indexes. Called once at startup.
  - Walk the file tree under `src/probos/`, record each `.py` file with its module docstring
  - Detect agent classes by finding subclasses of `BaseAgent`, `HeartbeatAgent`, `CognitiveAgent` using AST inspection (look for `class X(BaseAgent)` patterns)
  - For each agent class found, extract: `agent_type`, `tier`, `default_capabilities`, `intent_descriptors`, module path
  - Organize files into layers by directory: `substrate/`, `mesh/`, `consensus/`, `cognitive/`, `federation/`, `agents/`, `channels/`
  - Extract public method signatures from key classes: `ProbOSRuntime`, `TrustNetwork`, `IntentBus`, `HebbianRouter`, `DreamingEngine`, `ResourcePool`, `PoolScaler`
  - Parse `config.py` to extract all config model fields and their defaults

- `query(concept: str) -> dict[str, Any]` — Keyword-based lookup. Match `concept` against file names, docstrings, class names, method names, agent types. Return a dict with:
  ```python
  {
      "matching_files": list[dict],       # [{path, docstring, relevance}]
      "matching_agents": list[dict],      # [{type, tier, capabilities}]
      "matching_methods": list[dict],     # [{class, method, signature}]
      "layer": str | None                 # which architectural layer
  }
  ```

- `get_file_tree() -> dict[str, list[str]]` — Layer-organized file listing

- `get_agent_map() -> list[dict]` — All registered agent types with tier, capabilities, intent descriptors

- `get_layer_map() -> dict[str, list[str]]` — Files organized by architectural layer

- `get_config_schema() -> dict[str, Any]` — All config fields with types and defaults

- `get_api_surface(class_name: str) -> list[dict]` — Public methods for a given class with signatures

- `read_source(file_path: str, start_line: int | None = None, end_line: int | None = None) -> str` — Read source file contents (relative to source_root). Bounded to `src/probos/` only — cannot read files outside the source tree.

**Implementation notes:**
- Use `ast` module for parsing, not imports — avoids side effects
- No LLM calls — pure static analysis
- Keyword matching uses simple case-insensitive substring matching (not embeddings)
- Build time should be <1s for the current codebase (~87 files)

### `src/probos/cognitive/codebase_skill.py`

**Function:** `create_codebase_skill(index: CodebaseIndex) -> Skill`

Creates a `Skill` object (from `probos.types`) that any CognitiveAgent can use. The skill wraps the CodebaseIndex methods as intent handlers.

**Skill descriptor:**
```python
IntentDescriptor(
    name="codebase_knowledge",
    params={
        "action": "query|read_source|get_agent_map|get_layer_map|get_config_schema|get_api_surface",
        "query": "...",           # for action=query
        "file_path": "...",       # for action=read_source
        "start_line": "...",      # optional for read_source
        "end_line": "...",        # optional for read_source
        "class_name": "...",      # for action=get_api_surface
    },
    description="Query ProbOS's own source code architecture, agent registry, configuration, and API surface",
)
```

**Handler:** Dispatches based on `action` parameter, calls the corresponding `CodebaseIndex` method, returns the result as `IntentResult`.

### `src/probos/agents/medical/__init__.py`

Package root. Export all five agent classes.

### `src/probos/agents/medical/vitals_monitor.py`

**Class:** `VitalsMonitorAgent(HeartbeatAgent)`

- `agent_type = "vitals_monitor"`, `tier = "core"`, `pool = "medical"`
- Override `collect_metrics()` to gather:
  - Per-pool health ratios from `runtime.pools` (active / target)
  - Trust score statistics from `runtime.trust_network.all_scores()`: mean, min, count below 0.3
  - Dream consolidation state from `runtime.dream_scheduler`: is_dreaming, last report timestamp
  - Attention queue depth from `runtime.attention.queue_size`
  - Overall system health (mean agent confidence of ACTIVE agents)
- Define alert thresholds (configurable via `MedicalConfig`):
  - `pool_health_min: float = 0.5` — alert if any pool ratio drops below this
  - `trust_floor: float = 0.3` — alert if any agent trust drops below this
  - `health_floor: float = 0.6` — alert if overall system health drops below this
  - `max_trust_outliers: int = 3` — alert if more than N agents below trust_floor
- When thresholds are breached, broadcast an `medical_alert` intent with:
  ```python
  {
      "severity": "warning" | "critical",
      "metric": str,       # e.g., "pool_health", "trust_outlier", "system_health"
      "current_value": float,
      "threshold": float,
      "affected": str | list[str],  # pool name or agent IDs
      "timestamp": float
  }
  ```
- Collect interval: use the heartbeat interval (default 5s is fine)
- Keep a sliding window (last 12 readings = 60s) to detect trends, not just point-in-time spikes

### `src/probos/agents/medical/diagnostician.py`

**Class:** `DiagnosticianAgent(CognitiveAgent)`

- `agent_type = "diagnostician"`, `tier = "domain"`, `pool = "medical"`
- Handles `medical_alert` intent from Vitals Monitor
- Also handles `diagnose_system` intent (for on-demand diagnosis via shell: `/diagnose`)
- Instructions prompt the LLM to:
  - Analyze the alert data and current system state
  - Compare against baseline metrics (stored in episodic memory from previous diagnoses)
  - Identify root cause: is it an agent problem, pool problem, config problem, or load problem?
  - Produce a structured Diagnosis:
    ```python
    {
        "severity": "low" | "medium" | "high" | "critical",
        "category": "agent" | "pool" | "trust" | "memory" | "performance",
        "affected_components": list[str],
        "root_cause": str,
        "evidence": list[str],
        "recommended_treatment": str,
        "treatment_intent": str,  # intent name for Surgeon/Pharmacist
        "treatment_params": dict   # params for that intent
    }
    ```
- Store each diagnosis as an episodic memory episode for historical tracking
- Use `runtime.trust_network.summary()`, `runtime.status()`, and pool health data as context

### `src/probos/agents/medical/surgeon.py`

**Class:** `SurgeonAgent(CognitiveAgent)`

- `agent_type = "surgeon"`, `tier = "domain"`, `pool = "medical"`
- Handles `medical_remediate` intent from Diagnostician
- Actions available (selected by LLM based on diagnosis):
  - **recycle_agent**: Call `pool.check_health()` to trigger recycling, or `runtime.prune_agent(agent_id)` for permanent removal of consistently failing agents
  - **force_dream**: Call `runtime.dream_scheduler.force_dream()` to trigger immediate consolidation
  - **surge_pool**: Call `runtime.pool_scaler.request_surge(pool_name, extra=N)` to scale up underperforming pools
  - **restart_pool_health**: Reset the health check loop for a specific pool
- Each action is logged to the event log with category `"medical"` and event `"remediation"`
- After taking action, record the outcome: did the metric improve? Record as episodic memory for Pathologist
- Do NOT allow destructive actions (pruning) without first checking trust score — only prune agents below trust_floor with >10 observations

### `src/probos/agents/medical/pharmacist.py`

**Class:** `PharmacistAgent(CognitiveAgent)`

- `agent_type = "pharmacist"`, `tier = "domain"`, `pool = "medical"`
- Handles `medical_tune` intent from Diagnostician
- Analyzes trend data from Vitals Monitor's sliding window and historical diagnoses
- Produces configuration recommendations as structured output:
  ```python
  {
      "parameter": str,           # e.g., "dreaming.idle_threshold_seconds"
      "current_value": Any,
      "recommended_value": Any,
      "justification": str,
      "expected_impact": str,
      "confidence": float         # 0.0-1.0
  }
  ```
- Does NOT apply config changes directly — recommendations are logged and surfaced to the user
- Future: integrate with the human approval gate (Phase 30) for auto-application

### `src/probos/agents/medical/pathologist.py`

**Class:** `PathologistAgent(CognitiveAgent)`

- `agent_type = "pathologist"`, `tier = "domain"`, `pool = "medical"`
- Handles `medical_postmortem` intent, triggered when:
  - Escalation reaches Tier 3 (user consultation)
  - Consensus fails (INSUFFICIENT outcome)
  - An agent is pruned or crashes
- Analyzes the failure by querying:
  - Episodic memory for similar past failures (`runtime.recall_similar()`)
  - Trust history of involved agents
  - Hebbian routing weights to/from involved agents
  - **Codebase Knowledge Service** via `codebase_knowledge` skill — trace failures through source code to understand why a component behaves the way it does (e.g., "what logic determines routing for this intent type?")
- Produces a structured post-mortem:
  ```python
  {
      "failure_type": str,
      "involved_agents": list[str],
      "timeline": list[dict],     # sequence of events leading to failure
      "root_cause": str,
      "recurring": bool,          # has this pattern been seen before?
      "prior_occurrences": int,
      "recommendation": str,      # what should change to prevent recurrence
      "evolution_signal": str     # structured signal for future self-improvement pipeline
  }
  ```
- Store post-mortems as episodic memory episodes with `intent_type="medical_postmortem"`

## Files to Modify

### `src/probos/config.py`

Add `MedicalConfig` to `SystemConfig`:

```python
class MedicalConfig(BaseModel):
    enabled: bool = True
    vitals_interval_seconds: float = 5.0
    vitals_window_size: int = 12        # sliding window for trend detection
    pool_health_min: float = 0.5
    trust_floor: float = 0.3
    health_floor: float = 0.6
    max_trust_outliers: int = 3
    scheduled_diagnosis_interval: float = 300.0  # auto-diagnose every 5 minutes
```

Add `medical: MedicalConfig = MedicalConfig()` to `SystemConfig`.

### `src/probos/runtime.py`

- Build the `CodebaseIndex` at startup: `self.codebase_index = CodebaseIndex(Path("src/probos"))` then `await self.codebase_index.build()` (or sync since it's pure AST). Store as a runtime attribute.
- Register the `codebase_knowledge` skill via `create_codebase_skill(self.codebase_index)` so any CognitiveAgent can use it
- Register all five medical agent types in `_register_default_agents()`
- Create the `medical` pool in `start()` if `config.medical.enabled`
- Wire the Vitals Monitor with a runtime reference for metric collection
- Add `medical` to pool scaler exclusions (this pool should never be scaled)
- Hook the Pathologist into escalation Tier 3 completions: after user consultation resolves, broadcast `medical_postmortem` intent with the escalation context

### `config/system.yaml`

Add a `medical:` section with defaults (can be commented out):

```yaml
# medical:
#   enabled: true
#   vitals_interval_seconds: 5.0
#   trust_floor: 0.3
```

## Intent Routing

| Intent | Source | Handler |
|--------|--------|---------|
| `medical_alert` | VitalsMonitor | DiagnosticianAgent |
| `diagnose_system` | Shell (`/diagnose`) | DiagnosticianAgent |
| `medical_remediate` | DiagnosticianAgent | SurgeonAgent |
| `medical_tune` | DiagnosticianAgent | PharmacistAgent |
| `medical_postmortem` | Runtime (escalation hooks) | PathologistAgent |
| `codebase_knowledge` | Any CognitiveAgent | CodebaseIndex (via skill) |

## Testing

Create `tests/test_codebase_index.py` with:

### CodebaseIndex Tests
1. `test_index_builds_successfully` — build index on `src/probos/`, verify no errors, `_built` is True
2. `test_index_finds_agents` — verify agent_map includes known agents (e.g., `file_reader`, `introspect`)
3. `test_index_layer_map` — verify layers include `substrate`, `mesh`, `consensus`, `cognitive`
4. `test_index_query_trust` — query "trust" returns files from `consensus/trust.py`
5. `test_index_query_dreaming` — query "dreaming" returns files from `cognitive/dreaming.py`
6. `test_index_read_source` — read a known file, verify contents returned
7. `test_index_read_source_bounded` — attempt to read outside `src/probos/` raises error or returns empty
8. `test_index_api_surface` — get_api_surface("TrustNetwork") returns known methods like `get_score`, `record_outcome`
9. `test_codebase_skill_dispatch` — create skill, invoke with action=query, verify result structure

Create `tests/test_medical_team.py` with:

### Vitals Monitor Tests
10. `test_vitals_collects_metrics` — verify collect_metrics returns expected structure
11. `test_vitals_alert_on_low_pool_health` — mock a pool with active < target * pool_health_min, verify medical_alert is broadcast
12. `test_vitals_alert_on_trust_outlier` — inject a low-trust agent, verify alert
13. `test_vitals_no_alert_when_healthy` — all metrics normal, no alert broadcast
14. `test_vitals_sliding_window` — verify window size is respected, oldest readings dropped

### Diagnostician Tests
15. `test_diagnostician_handles_alert` — send medical_alert, verify structured Diagnosis returned
16. `test_diagnostician_identifies_pool_issue` — alert with pool_health metric → diagnosis category is "pool"
17. `test_diagnostician_identifies_trust_issue` — alert with trust_outlier metric → diagnosis category is "trust"
18. `test_diagnostician_stores_episode` — verify diagnosis is stored in episodic memory

### Surgeon Tests
19. `test_surgeon_force_dream` — diagnosis recommends dream cycle → verify force_dream() called
20. `test_surgeon_surge_pool` — diagnosis recommends scale-up → verify request_surge() called
21. `test_surgeon_wont_prune_without_observations` — agent below trust_floor but <10 observations → no prune
22. `test_surgeon_logs_remediation` — verify event_log entry with category "medical"

### Pharmacist Tests
23. `test_pharmacist_produces_recommendation` — send medical_tune intent, verify structured recommendation returned
24. `test_pharmacist_does_not_apply_changes` — verify no config mutation occurs (recommendations only)

### Pathologist Tests
25. `test_pathologist_handles_postmortem` — send medical_postmortem, verify structured post-mortem returned
26. `test_pathologist_detects_recurring_pattern` — inject prior similar episodes, verify `recurring: true`
27. `test_pathologist_stores_episode` — verify post-mortem stored in episodic memory
28. `test_pathologist_uses_codebase_knowledge` — verify pathologist can invoke codebase_knowledge skill to query architecture

### Integration Tests
29. `test_codebase_index_available_at_boot` — boot runtime, verify `runtime.codebase_index` is built and populated
30. `test_medical_pool_created_at_boot` — boot runtime with medical enabled, verify pool exists with 5 agents
31. `test_medical_pool_excluded_from_scaler` — verify medical pool is in scaler exclusions

## Constraints

- All CognitiveAgent medical agents use `tier = "domain"` and LLM tier `"fast"` (Ollama/local) to keep overhead low
- The Vitals Monitor must be extremely lightweight — no LLM calls, pure metric collection
- The CodebaseIndex must be lightweight — pure AST parsing, no LLM calls, build time <1s
- The CodebaseIndex is read-only — agents can read source code but never modify it through this service
- `read_source()` is bounded to `src/probos/` — cannot access files outside the source tree
- No agent should take destructive action without checking preconditions (trust observations > 10 for pruning, etc.)
- The medical pool is excluded from the pool scaler — it should never be scaled up or down
- All medical events use category `"medical"` in the event log for easy filtering
- Store diagnoses and post-mortems as episodic episodes so they benefit from dream consolidation

## Success Criteria

- CodebaseIndex builds at startup in <1s, populates agent map, layer map, config schema
- `query("trust")` returns relevant files from consensus layer
- `codebase_knowledge` skill is available to any CognitiveAgent
- Medical pool boots with 5 agents, all healthy
- Vitals Monitor detects injected anomalies (low trust, degraded pool) within one heartbeat cycle
- Diagnostician produces structured diagnosis from alert
- Surgeon successfully calls force_dream() and request_surge() when recommended
- Pharmacist produces recommendations without mutating config
- Pathologist stores post-mortems that can be recalled via episodic memory, uses codebase_knowledge for source-level analysis
- All 31 tests pass
- No performance regression on startup or during normal operation
