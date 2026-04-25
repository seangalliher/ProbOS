# AD-566a: Qualification Test Harness Infrastructure

**Status:** Ready for builder
**Lineage:** AD-566 (Crew Qualification Battery) → **AD-566a (Harness)** → AD-566b (Tier 1 Tests) → AD-566c (Drift Pipeline) → AD-566d (Tier 2) → AD-566e (Tier 3)
**Depends:** AD-434 (Ship's Records), AD-539 (gap-to-qualification bridge)
**Branch:** `ad-566a-qualification-harness`

---

## Context

The BF-103 accidental ablation study (2026-04-03) revealed that all collaborative
intelligence emerged without functional episodic memory — but this went undetected
for days because there was **no standardized measurement** to catch it. Agent
self-reports are unreliable (Vega reported 1 episode when she had 854).

AD-566 establishes objective psychometric measurement for ProbOS agents. AD-566a
is the foundational infrastructure: the protocol for defining tests, the engine for
running them, the store for persisting results, and the comparison API for detecting
change over time.

AD-566a builds the **harness** — the actual **tests** come in AD-566b through AD-566e.

### Existing Infrastructure to Reuse

| System | What to Reuse | Location |
|--------|---------------|----------|
| ConnectionFactory | Cloud-ready SQLite persistence | `storage/sqlite_factory.py` |
| RecallClassification | ACCURATE/CONFABULATED/CONTAMINATED/PARTIAL enum | `cognitive/guided_reminiscence.py` |
| Jaccard similarity | Text comparison scoring | `cognitive/similarity.py` |
| CognitiveProfile | Per-agent wellness tracking (memory_integrity_score, confabulation_rate) | `cognitive/counselor.py` |
| PersonalityTraits | Big Five model with `distance_from()` baseline drift | `crew_profile.py` |
| ProficiencyLevel | 7-level Dreyfus scale | `skill_framework.py` |
| VitalsMonitor | Engine snapshot pattern (`latest_snapshot` property) | `agents/medical/vitals_monitor.py` |
| EmergenceMetricsEngine | In-memory snapshot deque pattern | `cognitive/emergence_metrics.py` |
| Event system | `_emit_event_fn()` callable pattern | `events.py`, `cognitive/counselor.py:510` |

### Design Decision: SQLite for Results, Ship's Records for Reports

Test results need structured querying (latest per agent, baseline comparison, history)
→ SQLite via ConnectionFactory. Human-readable summary reports can be written to
Ship's Records as a future enhancement (AD-566c drift reports). Don't use Ship's
Records for raw results — git commits per test result would be noisy.

### Design Decision: Direct `handle_intent()` Invocation

Tests invoke agents via `agent.handle_intent(intent)` directly — NOT through the
IntentBus or DAG executor. This:
- Exercises the real cognitive pipeline (perceive → decide → act)
- Bypasses trust recording (DAG-level, not agent-level)
- Bypasses Hebbian updates (mesh-level)
- Bypasses Ward Room routing
- Only side effect to suppress: episode storage (see D4)

### Design Decision: Fast-Tier LLM

Test probes generate LLM calls. A full Tier 1 battery across 55 agents × 4 tests =
220 LLM calls. Tests SHOULD use the fast-tier model (same tier as spaced retrieval
therapy AD-541c and guided reminiscence AD-541d). The test gets the agent's LLM
client — it uses whatever model the agent is configured with.

---

## Principles Compliance

- **SOLID (S):** QualificationTest protocol, QualificationStore, QualificationHarness each have single responsibility
- **SOLID (O):** New tests added by implementing QualificationTest protocol — harness doesn't change
- **SOLID (I):** QualificationTest is a narrow Protocol — only `name`, `tier`, `threshold`, `run()`
- **SOLID (D):** Store uses ConnectionFactory abstraction, harness depends on Protocol not concrete classes
- **Law of Demeter:** Harness takes agent_id + runtime, resolves what it needs — tests don't reach through objects
- **Fail Fast:** Test execution failures log WARNING and return a failed TestResult — don't crash the harness
- **DRY:** Reuses ConnectionFactory, event system, existing scoring utilities
- **Cloud-Ready:** SQLite via ConnectionFactory — commercial overlay can swap to Postgres

---

## Deliverables

### D1 — Core Types (cognitive/qualification.py)

**`QualificationTest` Protocol:**

```python
@runtime_checkable
class QualificationTest(Protocol):
    """Protocol for a single qualification test.

    Implementations in AD-566b through AD-566e.
    """

    @property
    def name(self) -> str:
        """Unique test identifier, e.g. 'bfi2_personality_probe'."""
        ...

    @property
    def tier(self) -> int:
        """Test tier: 1 (baseline), 2 (domain), 3 (collective)."""
        ...

    @property
    def description(self) -> str:
        """Human-readable test description."""
        ...

    @property
    def threshold(self) -> float:
        """Pass/fail score threshold (0.0-1.0)."""
        ...

    async def run(self, agent_id: str, runtime: Any) -> "TestResult":
        """Execute the test and return scored result."""
        ...
```

**`TestResult` dataclass:**

```python
@dataclass(frozen=True)
class TestResult:
    """Immutable result of a single qualification test run."""
    agent_id: str           # Sovereign agent ID
    test_name: str          # Matches QualificationTest.name
    tier: int               # 1, 2, or 3
    score: float            # 0.0-1.0 normalized
    passed: bool            # score >= threshold
    timestamp: float        # time.time()
    duration_ms: float      # Test execution time
    is_baseline: bool = False  # True if this is the baseline measurement
    details: dict = field(default_factory=dict)  # Test-specific data
    error: str | None = None   # Non-None if test failed to execute
```

**`ComparisonResult` dataclass:**

```python
@dataclass(frozen=True)
class ComparisonResult:
    """Comparison of current test result against baseline."""
    agent_id: str
    test_name: str
    baseline_score: float
    current_score: float
    delta: float            # current - baseline
    percent_change: float   # (delta / baseline) * 100 if baseline > 0
    significant: bool       # abs(delta) > significance_threshold
    direction: str          # "improved" | "stable" | "declined"
```

Direction logic:
- `delta > significance_threshold` → "improved"
- `delta < -significance_threshold` → "declined"
- else → "stable"

### D2 — QualificationStore (cognitive/qualification.py)

SQLite persistence for test results. Follows the CounselorProfileStore / RetrievalPracticeEngine pattern.

**Schema:**

```sql
CREATE TABLE IF NOT EXISTS qualification_results (
    id TEXT PRIMARY KEY,              -- UUID
    agent_id TEXT NOT NULL,
    test_name TEXT NOT NULL,
    tier INTEGER NOT NULL,
    score REAL NOT NULL,
    passed INTEGER NOT NULL,          -- 0/1
    timestamp REAL NOT NULL,
    duration_ms REAL NOT NULL,
    is_baseline INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_qual_agent_test
    ON qualification_results(agent_id, test_name);

CREATE INDEX IF NOT EXISTS idx_qual_agent_baseline
    ON qualification_results(agent_id, is_baseline);
```

**Methods:**

```python
class QualificationStore:
    def __init__(self, data_dir: str | Path | None = None, connection_factory: Any = None):
        ...

    async def start(self) -> None:
        """Initialize DB connection and schema. Uses data_dir/qualification_results.db."""

    async def stop(self) -> None:
        """Close DB connection."""

    async def save_result(self, result: TestResult) -> None:
        """Persist a test result. Generates UUID for id."""

    async def get_baseline(self, agent_id: str, test_name: str) -> TestResult | None:
        """Get the baseline result for an agent+test. Returns the most recent
        row where is_baseline=1."""

    async def set_baseline(self, agent_id: str, test_name: str, result_id: str) -> None:
        """Mark a specific result as baseline. Clears any previous baseline
        for that agent+test pair (UPDATE is_baseline=0 WHERE ..., then
        UPDATE is_baseline=1 WHERE id=result_id)."""

    async def get_latest(self, agent_id: str, test_name: str) -> TestResult | None:
        """Get the most recent non-baseline result for an agent+test.
        ORDER BY timestamp DESC LIMIT 1."""

    async def get_history(
        self, agent_id: str, test_name: str, *, limit: int = 20
    ) -> list[TestResult]:
        """Get chronological history of results for an agent+test.
        ORDER BY timestamp DESC LIMIT limit."""

    async def get_agent_summary(self, agent_id: str) -> dict:
        """Aggregate summary across all tests for an agent. Returns:
        {
            "agent_id": str,
            "tests_run": int,
            "tests_passed": int,
            "pass_rate": float,
            "baseline_set": bool,
            "latest_results": {test_name: {score, passed, timestamp}},
        }
        """
```

**Serialization helpers:**
- `_result_to_row(result: TestResult) -> tuple` — for INSERT
- `_row_to_result(row: tuple) -> TestResult` — for SELECT reconstruction

Use `json.dumps(result.details)` / `json.loads(row["details_json"])` for the
details dict, following the CognitiveProfile `profile_json` pattern.

### D3 — QualificationHarness Engine (cognitive/qualification.py)

The main engine. Manages test registry, execution, baseline capture, and comparison.

```python
class QualificationHarness:
    def __init__(
        self,
        store: QualificationStore,
        emit_event_fn: Any | None = None,
        config: "QualificationConfig | None" = None,
    ):
        self._store = store
        self._emit_event_fn = emit_event_fn
        self._config = config or QualificationConfig()
        self._tests: dict[str, QualificationTest] = {}
        self._latest_results: dict[str, TestResult] = {}  # agent_id:test_name → result

    def register_test(self, test: QualificationTest) -> None:
        """Register a test implementation. Called during startup by AD-566b+ modules."""
        self._tests[test.name] = test

    @property
    def registered_tests(self) -> dict[str, QualificationTest]:
        """Read-only view of registered tests."""

    async def run_test(
        self, agent_id: str, test_name: str, runtime: Any
    ) -> TestResult:
        """Run a single test for an agent.

        1. Look up test in registry (KeyError if not found)
        2. Execute test.run(agent_id, runtime) with timeout
        3. If baseline_auto_capture and no baseline exists, mark as baseline
        4. Save result to store
        5. Emit QUALIFICATION_TEST_COMPLETE event
        6. Update _latest_results cache
        7. Return TestResult
        """

    async def run_tier(
        self, agent_id: str, tier: int, runtime: Any
    ) -> list[TestResult]:
        """Run all registered tests for a specific tier."""

    async def run_all(
        self, agent_id: str, runtime: Any
    ) -> list[TestResult]:
        """Run all registered tests for an agent."""

    async def run_baseline(
        self, agent_id: str, runtime: Any
    ) -> list[TestResult]:
        """Run all tests and mark results as baseline.
        Forces is_baseline=True regardless of auto_capture setting."""

    async def compare(
        self, agent_id: str, test_name: str
    ) -> ComparisonResult | None:
        """Compare latest result against baseline.
        Returns None if no baseline or no current result exists."""

    async def compare_all(
        self, agent_id: str
    ) -> dict[str, ComparisonResult]:
        """Compare all tests for an agent. Returns {test_name: ComparisonResult}."""

    async def get_agent_summary(self, agent_id: str) -> dict:
        """Delegate to store.get_agent_summary()."""

    @property
    def latest_snapshot(self) -> dict | None:
        """Most recent results dict for VitalsMonitor integration.
        Returns {agent_id: {test_name: score}} or None if no results."""
```

**Error handling in `run_test()`:**

```python
async def run_test(self, agent_id: str, test_name: str, runtime: Any) -> TestResult:
    test = self._tests.get(test_name)
    if test is None:
        raise KeyError(f"Unknown test: {test_name}")

    t0 = time.time()
    try:
        result = await asyncio.wait_for(
            test.run(agent_id, runtime),
            timeout=self._config.test_timeout_seconds,
        )
    except asyncio.TimeoutError:
        result = TestResult(
            agent_id=agent_id,
            test_name=test_name,
            tier=test.tier,
            score=0.0,
            passed=False,
            timestamp=time.time(),
            duration_ms=(time.time() - t0) * 1000,
            error="Test timed out",
        )
    except Exception as exc:
        result = TestResult(
            agent_id=agent_id,
            test_name=test_name,
            tier=test.tier,
            score=0.0,
            passed=False,
            timestamp=time.time(),
            duration_ms=(time.time() - t0) * 1000,
            error=str(exc),
        )

    # Auto-baseline on first run
    if self._config.baseline_auto_capture and result.error is None:
        existing = await self._store.get_baseline(agent_id, test_name)
        if existing is None:
            result = dataclasses.replace(result, is_baseline=True)
            if self._event_bus:
                self._event_bus.emit(
                    "qualification_baseline_set",
                    {"agent_id": agent_id, "test_name": test_name, "score": result.score},
                )

    await self._store.save_result(result)
    self._latest_results[f"{agent_id}:{test_name}"] = result

    if self._emit_event_fn:
        self._emit_event_fn(
            "qualification_test_complete",
            {
                "agent_id": agent_id,
                "test_name": test_name,
                "score": result.score,
                "passed": result.passed,
                "is_baseline": result.is_baseline,
            },
        )

    return result
```

### D4 — Episode Suppression (cognitive_agent.py)

Prevent test interactions from polluting episodic memory. Add a guard at the top
of `_store_action_episode()`:

```python
async def _store_action_episode(self, intent, observation, report):
    # AD-566a: Skip episode storage for qualification test interactions
    if intent.params.get("_qualification_test"):
        return
    # ... rest of existing method unchanged ...
```

This is a 2-line addition. Tests call `agent.handle_intent(intent)` with
`params={"_qualification_test": True, ...}` to suppress side effects.

**What this suppresses:**
- Episode storage in EpisodicMemory (the only agent-level side effect)

**What is already not triggered by direct `handle_intent()`:**
- Trust recording (DAG executor level)
- Hebbian weight updates (mesh level)
- Ward Room posting (WardRoomRouter level)

### D5 — Event Types (events.py)

Add two event type constants to the `EventType` enum. Find the existing event
constant definitions and add:

```python
QUALIFICATION_TEST_COMPLETE = "qualification_test_complete"  # AD-566a
QUALIFICATION_BASELINE_SET = "qualification_baseline_set"    # AD-566a
```

These are `EventType` enum members (see `events.py` — `class EventType(str, Enum)`),
not standalone string constants. Follow the naming pattern of existing members
(e.g., `DREAM_COMPLETE`, `EMERGENCE_METRICS_UPDATED`).

### D6 — Configuration (config.py)

Add `QualificationConfig` to config.py:

```python
class QualificationConfig(BaseModel):
    """Configuration for the Crew Qualification Battery (AD-566)."""

    enabled: bool = True
    baseline_auto_capture: bool = True  # First run auto-sets baseline
    significance_threshold: float = 0.15  # 15% delta = significant change
    test_timeout_seconds: float = 60.0  # Per-test timeout
```

Add a field to `SystemConfig`:

```python
qualification: QualificationConfig = QualificationConfig()
```

### D7 — Startup Wiring (startup/cognitive_services.py)

Wire the QualificationHarness into the startup pipeline. Follow the pattern used
for CounselorProfileStore in `startup/agent_fleet.py`:

```python
# AD-566a: Qualification Harness
from probos.cognitive.qualification import QualificationHarness, QualificationStore

qual_store = QualificationStore(data_dir=data_dir)
await qual_store.start()
rt._qualification_store = qual_store

qual_harness = QualificationHarness(
    store=qual_store,
    emit_event_fn=emit_event_fn,
    config=rt.config.qualification,
)
rt._qualification_harness = qual_harness
```

The `emit_event_fn` callable is NOT currently available in `cognitive_services.py`.
Two options (builder should choose the simpler one):
1. Pass `emit_event_fn=None` for now — events will be wired when AD-566b adds tests
2. Thread `emit_event_fn` through the function signature like `startup/dreaming.py` does

Option 1 is preferred — keep AD-566a minimal. The harness already handles `None`
gracefully (checks `if self._emit_event_fn:` before calling).

Add to the shutdown sequence (`startup/shutdown.py`):

```python
# AD-566a: Qualification Store
qual_store = getattr(rt, "_qualification_store", None)
if qual_store is not None:
    await qual_store.stop()
```

Look at how other engines (EmergenceMetricsEngine, RetrievalPracticeEngine) are
started/stopped to match the exact pattern.

---

## Test Spec

**New file:** `tests/test_ad566a_qualification_harness.py`

### D1 — Core Types (4 tests)

| # | Test | Asserts |
|---|------|---------|
| 1 | `test_test_result_frozen` | `TestResult` is frozen dataclass — cannot mutate |
| 2 | `test_test_result_defaults` | Default `is_baseline=False`, `details={}`, `error=None` |
| 3 | `test_comparison_result_improved` | delta > threshold → direction="improved" |
| 4 | `test_comparison_result_declined` | delta < -threshold → direction="declined" |

### D2 — QualificationStore (5 tests)

| # | Test | Asserts |
|---|------|---------|
| 5 | `test_store_save_and_load` | Save TestResult, get_latest returns it with matching fields |
| 6 | `test_store_baseline_set_and_get` | `set_baseline()` marks result, `get_baseline()` returns it |
| 7 | `test_store_baseline_replaces_previous` | Setting new baseline clears old one (only one baseline per agent+test) |
| 8 | `test_store_history_chronological` | Multiple results returned newest-first, respects limit |
| 9 | `test_store_agent_summary` | Summary aggregates across tests — tests_run, pass_rate, etc. |

### D3 — QualificationHarness (7 tests)

| # | Test | Asserts |
|---|------|---------|
| 10 | `test_harness_register_test` | `register_test()` → test appears in `registered_tests` |
| 11 | `test_harness_run_test_basic` | Run mock test → TestResult stored in DB, returned |
| 12 | `test_harness_auto_baseline` | First run auto-captures baseline when `baseline_auto_capture=True` |
| 13 | `test_harness_no_auto_baseline` | `baseline_auto_capture=False` → first run is NOT baseline |
| 14 | `test_harness_run_tier` | Register 2 tier-1 tests + 1 tier-2 → `run_tier(tier=1)` runs only tier-1 tests |
| 15 | `test_harness_compare` | Baseline at 0.8, current at 0.6 → ComparisonResult with delta=-0.2, direction="declined" |
| 16 | `test_harness_timeout` | Slow test exceeds timeout → TestResult with error="Test timed out", score=0.0 |

### D4 — Episode Suppression (1 test)

| # | Test | Asserts |
|---|------|---------|
| 17 | `test_qualification_test_skips_episode_storage` | Call `_store_action_episode()` with `intent.params["_qualification_test"]=True` → no episode stored |

### D5 — Events (1 test)

| # | Test | Asserts |
|---|------|---------|
| 18 | `test_harness_emits_events` | Run test → `"qualification_test_complete"` emitted via `emit_event_fn`. Auto-baseline → `"qualification_baseline_set"` emitted. Use a mock callable to capture. |

### D6 — Config (1 test)

| # | Test | Asserts |
|---|------|---------|
| 19 | `test_qualification_config_defaults` | `enabled=True`, `baseline_auto_capture=True`, `significance_threshold=0.15`, `test_timeout_seconds=60.0` |

**Total: 19 tests** in 1 new test file.

### Mock Test Helper

Tests need a mock QualificationTest implementation:

```python
class MockQualificationTest:
    """A test that always returns a configurable score."""

    def __init__(self, name="mock_test", tier=1, threshold=0.5, score=0.75):
        self._name = name
        self._tier = tier
        self._threshold = threshold
        self._score = score

    @property
    def name(self) -> str:
        return self._name

    @property
    def tier(self) -> int:
        return self._tier

    @property
    def description(self) -> str:
        return "Mock test for harness validation"

    @property
    def threshold(self) -> float:
        return self._threshold

    async def run(self, agent_id: str, runtime: Any) -> TestResult:
        return TestResult(
            agent_id=agent_id,
            test_name=self._name,
            tier=self._tier,
            score=self._score,
            passed=self._score >= self._threshold,
            timestamp=time.time(),
            duration_ms=1.0,
        )
```

For store tests, use an in-memory SQLite connection (`:memory:`) or tmp_path
fixture — follow the pattern in existing store tests.

---

## Files to Modify

| File | Action | Changes |
|------|--------|---------|
| `src/probos/cognitive/qualification.py` | **Create** | D1: types (QualificationTest, TestResult, ComparisonResult). D2: QualificationStore. D3: QualificationHarness. |
| `src/probos/cognitive/cognitive_agent.py` | Edit | D4: 2-line guard in `_store_action_episode()` |
| `src/probos/events.py` | Edit | D5: 2 event type constants |
| `src/probos/config.py` | Edit | D6: QualificationConfig + SystemConfig field |
| `src/probos/startup/cognitive_services.py` | Edit | D7: Harness + Store startup (follow `agent_fleet.py` CounselorProfileStore pattern) |
| `src/probos/startup/shutdown.py` | Edit | D7: Store shutdown |
| `tests/test_ad566a_qualification_harness.py` | **Create** | 19 tests |

**7 files** (2 new, 5 edits). No dataclass changes to existing types. No migration.
No new dependencies.

---

## Scope Exclusions

| Excluded | Reason | Future |
|----------|--------|--------|
| Actual test implementations (BFI, recall, confabulation, MTI) | AD-566b | Next AD |
| Drift detection pipeline (scheduled execution, statistical alerts) | AD-566c | After 566b |
| Domain-specific tests (ToM, SWE, security) | AD-566d | After 566a |
| Collective tests (CBS, IRT, c-factor) | AD-566e | After 566a |
| HTTP API endpoints | Not needed until tests exist to expose | AD-566b or later |
| VitalsMonitor integration | Need actual metrics to surface | AD-566c |
| Counselor integration (drift → wellness check) | Need drift pipeline | AD-566c |
| Ship's Records summary reports | Need test data to summarize | AD-566c |
| Dream cycle integration | Drift pipeline concern | AD-566c |
| AD-539 gap record generation on test failure | Need test implementations first | AD-566b |

---

## Builder Instructions

1. Read existing patterns: `cognitive/emergence_metrics.py` (engine pattern),
   `cognitive/counselor.py:277` (CounselorProfileStore SQLite pattern),
   `cognitive/retrieval_practice.py` (ConnectionFactory + start/stop lifecycle),
   `startup/agent_fleet.py:109` (CounselorProfileStore startup wiring — follow this for D7)
2. Create `cognitive/qualification.py` with all D1-D3 deliverables in one file
3. The `QualificationTest` protocol uses `typing.Protocol` + `@runtime_checkable`
4. `TestResult` is `@dataclass(frozen=True)` — immutable like Episode
5. **Do NOT import or depend on any specific agent class** — the harness is
   agent-type-agnostic. It takes `agent_id: str` and `runtime: Any`
6. Follow the existing `ConnectionFactory` protocol — do NOT call
   `aiosqlite.connect()` directly
7. Run: `python -m pytest tests/test_ad566a_qualification_harness.py -x -v`
8. Run: `python -m pytest tests/test_fallback_learning.py -x -q` (regression —
   uses `_store_action_episode`)
9. Run: `python -m pytest tests/ -k "cognitive_agent" -x -q` (regression)
10. Update tracking files: `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md`
