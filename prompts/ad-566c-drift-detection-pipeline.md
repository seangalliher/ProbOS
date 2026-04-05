# AD-566c: Drift Detection Pipeline

**Depends:** AD-566a (harness) ✅, AD-566b (Tier 1 tests) ✅
**Blocked by:** Nothing — both dependencies are complete
**Enables:** AD-566d (Tier 2 domain tests), AD-566e (Tier 3 collective tests), longitudinal analysis

---

## Goal

Build the automated pipeline that **periodically runs Tier 1 qualification tests**, detects statistically significant drift from baseline, and routes alerts to Counselor (2σ) and Bridge (3σ). This is the operational layer that makes the qualification battery useful — without it, tests only run on manual invocation.

The pipeline answers: **"Is this agent still behaving like itself?"**

Academic grounding:
- Chen, Zaharia, Zou (2023): GPT-4 capabilities drifted 33 percentage points in 3 months — proving periodic measurement is essential
- Jeong (2026, MTI): Behavioral profiling with deviation thresholds detects temperamental drift
- Khanal et al. (2026): Capability ≠ reliability — agents can be capable but behaviorally inconsistent

---

## Deliverables

### D1 — DriftDetector Engine (`src/probos/cognitive/drift_detector.py`, NEW)

The core statistical engine. Computes drift signals from qualification test history.

```python
class DriftSignal:
    """Result of drift analysis for one agent+test pair."""
    agent_id: str
    test_name: str
    current_score: float
    baseline_score: float
    mean_score: float       # running mean from history
    std_dev: float          # standard deviation from history
    z_score: float          # how many SDs from the mean
    direction: str          # "improved" | "stable" | "declined"
    severity: str           # "normal" | "warning" | "critical"
    sample_count: int       # how many historical data points
    # Frozen dataclass

class DriftReport:
    """Aggregated drift analysis for one agent across all tests."""
    agent_id: str
    timestamp: float
    signals: list[DriftSignal]
    overall_severity: str   # worst severity across all signals
    drift_detected: bool    # any signal at warning or critical
    # Frozen dataclass

class DriftDetector:
    """Statistical drift detection engine.

    Computes z-scores from QualificationStore history and classifies
    drift severity against configurable sigma thresholds.
    """

    def __init__(
        self,
        store: QualificationStore,
        config: QualificationConfig,
    ) -> None: ...

    async def analyze_agent(self, agent_id: str, test_names: list[str]) -> DriftReport:
        """Compute drift signals for an agent across specified tests.

        For each test:
        1. Fetch history from store (get_history, limit=config.drift_history_window)
        2. Compute mean and std_dev from historical scores
        3. Get latest result
        4. Compute z_score = (latest - mean) / std_dev (guard against std_dev=0)
        5. Classify severity:
           - |z_score| < config.drift_warning_sigma → "normal"
           - |z_score| >= config.drift_warning_sigma → "warning" (Counselor alert)
           - |z_score| >= config.drift_critical_sigma → "critical" (Bridge alert)
        6. Compute direction from delta (current - baseline)

        Minimum sample count: config.drift_min_samples (default 3).
        If fewer samples exist, return severity="normal" (insufficient data).
        """

    async def analyze_all_agents(
        self, agent_ids: list[str], test_names: list[str]
    ) -> list[DriftReport]:
        """Run drift analysis for multiple agents. Returns list of DriftReports."""
```

**Statistical approach:** Simple z-score against running history. Not a sophisticated time-series model — we're detecting whether the agent's current score is abnormally far from its own historical average. This is the right starting point given our data volume (weekly tests = ~4 data points/month).

**Guard against std_dev=0:** If all historical scores are identical (common early on), treat as "normal" — no drift detectable yet. Use `max(std_dev, 1e-9)` to avoid division by zero, but flag `sample_count` so callers know the result is low-confidence.

### D2 — QualificationConfig Extension (`src/probos/config.py`, EDIT)

Add drift detection configuration to the existing `QualificationConfig`:

```python
class QualificationConfig(BaseModel):
    """Configuration for the Crew Qualification Battery (AD-566)."""

    enabled: bool = True
    baseline_auto_capture: bool = True
    significance_threshold: float = 0.15
    test_timeout_seconds: float = 60.0

    # AD-566c: Drift Detection Pipeline
    drift_check_enabled: bool = True
    drift_check_interval_seconds: float = 604800.0  # 1 week (7 days)
    drift_warning_sigma: float = 2.0    # Counselor alert threshold
    drift_critical_sigma: float = 3.0   # Bridge/Captain alert threshold
    drift_min_samples: int = 3          # Minimum data points before drift analysis
    drift_history_window: int = 20      # Max historical results for stats
    drift_cooldown_seconds: float = 3600.0  # Min time between alerts for same agent+test
```

### D3 — New Event Type (`src/probos/events.py`, EDIT)

Add after line 141 (after `QUALIFICATION_BASELINE_SET`):

```python
QUALIFICATION_DRIFT_DETECTED = "qualification_drift_detected"  # AD-566c
```

Event payload (emitted by the scheduler, not the detector):
```python
{
    "agent_id": str,
    "test_name": str,
    "z_score": float,
    "severity": str,           # "warning" or "critical"
    "current_score": float,
    "mean_score": float,
    "baseline_score": float,
    "direction": str,          # "improved" | "stable" | "declined"
    "sample_count": int,
}
```

### D4 — DriftScheduler (`src/probos/cognitive/drift_detector.py`, same file as D1)

The periodic runner that invokes drift analysis on a schedule.

```python
class DriftScheduler:
    """Periodic drift detection scheduler.

    Runs Tier 1 qualification tests on a configurable interval,
    performs drift analysis, and emits events for detected drift.
    Integrates with the existing ProactiveCognitiveLoop pattern.
    """

    def __init__(
        self,
        harness: QualificationHarness,
        detector: DriftDetector,
        emit_event_fn: Callable | None = None,
        config: QualificationConfig | None = None,
    ) -> None:
        self._harness = harness
        self._detector = detector
        self._emit_event_fn = emit_event_fn
        self._config = config or QualificationConfig()
        self._task: asyncio.Task | None = None
        self._running = False
        self._last_check: dict[str, float] = {}  # agent_id:test_name → timestamp (cooldown)
        self._last_run_time: float = 0.0

    async def start(self) -> None:
        """Start the periodic drift check loop."""
        if not self._config.drift_check_enabled:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        """Stop the periodic drift check loop."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run_loop(self) -> None:
        """Main loop — follows ProactiveCognitiveLoop pattern (proactive.py:265-274)."""
        while self._running:
            try:
                await self._run_cycle()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("DriftScheduler cycle error")
            await asyncio.sleep(self._config.drift_check_interval_seconds)

    async def _run_cycle(self) -> None:
        """Single drift check cycle.

        1. Get all registered test names (Tier 1 only)
        2. Get all active crew agent IDs from the runtime
        3. For each agent: run_tier(agent_id, 1, runtime)
        4. For each agent: analyze drift via DriftDetector
        5. For each drift signal at warning/critical: emit event (with cooldown)
        """

    async def run_now(self, agent_ids: list[str] | None = None) -> list[DriftReport]:
        """On-demand drift check (for API/manual invocation).

        If agent_ids is None, checks all active crew agents.
        Returns DriftReports for all analyzed agents.
        Skips test execution if recent results exist (within interval).
        """

    @property
    def last_run_time(self) -> float:
        """Timestamp of last completed drift check cycle."""

    @property
    def latest_reports(self) -> dict[str, DriftReport]:
        """Most recent DriftReport per agent_id. For VitalsMonitor integration."""
```

**Cooldown:** Use `_last_check` dict to avoid spamming alerts. If an alert was emitted for `agent_id:test_name` within `drift_cooldown_seconds`, skip re-emission. The cooldown operates per-signal, not per-agent — an agent can have warnings on different tests simultaneously.

**Runtime access:** The scheduler needs access to active crew agent IDs. It receives a runtime reference. Enumerate crew agents via `runtime.pools` + `is_crew_agent()` from `probos.crew_utils`. Pattern: iterate `runtime.pools.values()`, get `pool.healthy_agents`, filter with `is_crew_agent(agent)`, collect `agent.id`. This mirrors how ProactiveCognitiveLoop and VitalsMonitor enumerate agents.

### D5 — VitalsMonitor Integration (`src/probos/agents/medical/vitals_monitor.py`, EDIT)

Add qualification drift metrics to VitalsMonitor's `collect_metrics()` method. Follow the exact pattern used for emergence metrics (lines 118-124) and notebook quality (lines 126-133):

```python
# AD-566c: Qualification drift metrics
_drift_scheduler = getattr(rt, "_drift_scheduler", None)
if _drift_scheduler:
    _reports = _drift_scheduler.latest_reports
    if _reports:
        drift_agents_warning = sum(
            1 for r in _reports.values() if r.overall_severity == "warning"
        )
        drift_agents_critical = sum(
            1 for r in _reports.values() if r.overall_severity == "critical"
        )
        metrics["qualification_drift_warning_count"] = drift_agents_warning
        metrics["qualification_drift_critical_count"] = drift_agents_critical
        metrics["qualification_last_check"] = _drift_scheduler.last_run_time
```

Also add to `_check_thresholds()`: if `qualification_drift_critical_count > 0`, emit a warning-level alert (the Bridge alert for specific agents is handled by BridgeAlertService in D6).

### D6 — Bridge Alert Integration (`src/probos/bridge_alerts.py`, EDIT)

Add a new `check_qualification_drift()` method to `BridgeAlertService`. Follow the existing `check_*()` pattern (e.g., `check_convergence` at line 349):

```python
def check_qualification_drift(self, drift_reports: list[DriftReport]) -> list[BridgeAlert]:
    """AD-566c: Evaluate qualification drift and emit bridge alerts.

    - Warning severity (2σ): ADVISORY alert, routes to Medical department
    - Critical severity (3σ): ALERT severity, routes to Bridge (all-hands)
    """
    alerts: list[BridgeAlert] = []
    for report in drift_reports:
        if not report.drift_detected:
            continue
        for signal in report.signals:
            if signal.severity == "critical":
                key = f"qual_drift_critical:{signal.agent_id}:{signal.test_name}"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()),
                        severity=AlertSeverity.ALERT,
                        source="qualification_drift",
                        alert_type="qualification_drift_critical",
                        title=f"Critical Drift — {signal.agent_id[:20]} on {signal.test_name}",
                        detail=(
                            f"Agent {signal.agent_id} shows {signal.z_score:.1f}σ deviation "
                            f"on {signal.test_name} (score: {signal.current_score:.2f}, "
                            f"mean: {signal.mean_score:.2f}, baseline: {signal.baseline_score:.2f}). "
                            f"Direction: {signal.direction}. Automatic investigation recommended."
                        ),
                        department=None,  # All-hands for critical
                        dedup_key=key,
                        related_agent_id=signal.agent_id,
                    )
                    self._record(a)
                    alerts.append(a)
            elif signal.severity == "warning":
                key = f"qual_drift_warning:{signal.agent_id}:{signal.test_name}"
                if self._should_emit(key):
                    a = BridgeAlert(
                        id=str(uuid.uuid4()),
                        severity=AlertSeverity.ADVISORY,
                        source="qualification_drift",
                        alert_type="qualification_drift_warning",
                        title=f"Drift Detected — {signal.agent_id[:20]} on {signal.test_name}",
                        detail=(
                            f"Agent {signal.agent_id} shows {signal.z_score:.1f}σ deviation "
                            f"on {signal.test_name} (score: {signal.current_score:.2f}, "
                            f"mean: {signal.mean_score:.2f}). Direction: {signal.direction}."
                        ),
                        department="medical",  # Route to Medical (Counselor)
                        dedup_key=key,
                        related_agent_id=signal.agent_id,
                    )
                    self._record(a)
                    alerts.append(a)
    return alerts
```

### D7 — Counselor Integration (`src/probos/cognitive/counselor.py`, EDIT)

Subscribe to the new `QUALIFICATION_DRIFT_DETECTED` event. Follow the existing pattern (event subscription at line ~574-588, handler methods like `_on_trust_cascade`):

**Event subscription addition** (in the subscription list, after RETRIEVAL_PRACTICE_CONCERN):
```python
EventType.QUALIFICATION_DRIFT_DETECTED: self._on_qualification_drift,
```

**Handler method:**
```python
async def _on_qualification_drift(self, data: dict[str, Any]) -> None:
    """AD-566c: Respond to qualification drift detection.

    Warning severity: Track in agent's cognitive profile, update wellness.
    Critical severity: Trigger full assessment + therapeutic DM.
    """
    agent_id = data.get("agent_id", "")
    test_name = data.get("test_name", "")
    severity = data.get("severity", "warning")
    z_score = data.get("z_score", 0.0)
    direction = data.get("direction", "unknown")

    if not agent_id or agent_id == self.id:
        return

    callsign = self._resolve_agent_callsign(agent_id)

    if severity == "critical":
        # Full assessment — follow the pattern from _on_self_monitoring_concern (line 858)
        metrics = self._gather_agent_metrics(agent_id)
        assessment = self.assess_agent(
            agent_id=agent_id,
            current_trust=metrics["trust_score"],
            current_confidence=metrics["confidence"],
            hebbian_avg=metrics["hebbian_avg"],
            success_rate=metrics["success_rate"],
            personality_drift=metrics["personality_drift"],
            trigger="qualification_drift_critical",
        )
        await self._save_profile_and_assessment(agent_id, assessment)

        # Therapeutic DM
        message = (
            f"@{callsign}, the qualification battery has detected a significant "
            f"change in your **{test_name}** scores ({z_score:.1f}σ deviation, "
            f"direction: {direction}). I'd like to check in with you — "
            f"how are you experiencing your work lately? Have you noticed "
            f"any changes in how you approach tasks?"
        )
        await self._send_therapeutic_dm(agent_id, callsign, message)
    else:
        # Warning: track but don't DM unless wellness is already low
        logger.info(
            "AD-566c: Drift warning for %s on %s (z=%.1f, dir=%s)",
            callsign, test_name, z_score, direction,
        )
```

### D8 — Runtime Wiring (`src/probos/runtime.py`, EDIT)

Wire the DriftScheduler into the runtime startup. Add after the existing qualification harness wiring (after line ~1155):

```python
# AD-566c: Drift Detection Pipeline
self._drift_scheduler: Any = None
try:
    from probos.cognitive.drift_detector import DriftDetector, DriftScheduler
    if self._qualification_harness and self._qualification_store:
        detector = DriftDetector(
            store=self._qualification_store,
            config=self.config.qualification,
        )
        self._drift_scheduler = DriftScheduler(
            harness=self._qualification_harness,
            detector=detector,
            emit_event_fn=self._emit_event,
            config=self.config.qualification,
        )
except Exception as e:
    logger.warning("DriftScheduler init failed: %s — continuing without", e)
```

Start the scheduler in the appropriate startup phase (same phase as qualification harness, after fleet agents start so agent IDs are available):

```python
if self._drift_scheduler:
    # Pass runtime reference for agent ID enumeration
    await self._drift_scheduler.start()
```

And shutdown in `src/probos/startup/shutdown.py` (add BEFORE the qualification store shutdown at line ~182, since the scheduler depends on the store):
```python
# AD-566c: Stop drift scheduler
drift_scheduler = getattr(runtime, "_drift_scheduler", None)
if drift_scheduler is not None:
    await drift_scheduler.stop()
    runtime._drift_scheduler = None
```

**CRITICAL:** The scheduler start must happen AFTER agent fleet initialization AND after at least one baseline run has occurred (otherwise all drift checks return "insufficient data"). The scheduler itself handles the "insufficient data" case gracefully (returns severity="normal"), so ordering is a recommendation, not a hard requirement.

### D9 — Runtime Integration for Drift Checks

The DriftScheduler needs to know which agents to test and needs access to the runtime to call `run_tier()`. Two approaches — choose whichever is cleaner:

**Option A (preferred): Pass runtime reference to scheduler**
```python
self._drift_scheduler = DriftScheduler(
    harness=self._qualification_harness,
    detector=detector,
    emit_event_fn=self._emit_event,
    config=self.config.qualification,
    runtime=self,  # DriftScheduler enumerates crew agents via runtime.pools
                   # + is_crew_agent() and passes runtime to harness.run_tier()
)
```

**Option B: Pass callable closures**
```python
from probos.crew_utils import is_crew_agent

self._drift_scheduler = DriftScheduler(
    harness=self._qualification_harness,
    detector=detector,
    emit_event_fn=self._emit_event,
    config=self.config.qualification,
    get_agent_ids_fn=lambda: [
        a.id for pool in self.pools.values()
        for a in pool.healthy_agents
        if is_crew_agent(a)
    ],
    get_runtime_fn=lambda: self,
)
```

Use whichever avoids circular imports. Option A is simpler. The scheduler only needs:
1. A way to get active crew agent IDs
2. A runtime reference to pass to `harness.run_tier(agent_id, 1, runtime)`

---

## Integration Points Summary

| System | Integration | Direction |
|---|---|---|
| QualificationHarness (AD-566a) | `run_tier()` for test execution, registered tests | DriftScheduler → Harness |
| QualificationStore (AD-566a) | `get_history()` for statistical computation | DriftDetector → Store |
| EventType (events.py) | `QUALIFICATION_DRIFT_DETECTED` new event | DriftScheduler → EventBus |
| CounselorAgent (AD-505) | Subscribe + therapeutic response | EventBus → Counselor |
| VitalsMonitor | Surface drift counts as health metrics | DriftScheduler → VitalsMonitor |
| BridgeAlertService | `check_qualification_drift()` for Captain alerts | DriftScheduler → BridgeAlerts |
| Runtime | Wiring + shutdown | startup/shutdown lifecycle |
| QualificationConfig | New drift config fields | config.py |

---

## Acceptance Criteria

### Minimum test count: 30

### Test breakdown:

**DriftDetector tests (~12):**
- `test_drift_signal_normal` — z-score within bounds → severity "normal"
- `test_drift_signal_warning` — z-score >= 2σ → severity "warning"
- `test_drift_signal_critical` — z-score >= 3σ → severity "critical"
- `test_drift_direction_improved` — positive delta → "improved"
- `test_drift_direction_declined` — negative delta → "declined"
- `test_drift_direction_stable` — small delta → "stable"
- `test_drift_insufficient_samples` — fewer than `drift_min_samples` → "normal" (insufficient data)
- `test_drift_zero_stddev` — all identical scores → "normal" (no variance)
- `test_drift_report_overall_severity` — worst signal determines report severity
- `test_drift_report_multiple_tests` — analyzes across all specified tests
- `test_drift_history_window` — respects `drift_history_window` limit
- `test_drift_config_thresholds` — custom sigma thresholds apply correctly

**DriftScheduler tests (~8):**
- `test_scheduler_start_stop` — starts and stops cleanly
- `test_scheduler_disabled` — `drift_check_enabled=False` → does not start
- `test_scheduler_run_now` — on-demand drift check returns DriftReports
- `test_scheduler_emits_event_on_warning` — emits `QUALIFICATION_DRIFT_DETECTED` for warning
- `test_scheduler_emits_event_on_critical` — emits `QUALIFICATION_DRIFT_DETECTED` for critical
- `test_scheduler_cooldown` — does not re-emit within `drift_cooldown_seconds`
- `test_scheduler_latest_reports` — `latest_reports` property returns cached results
- `test_scheduler_no_event_on_normal` — no event emitted when all signals normal

**BridgeAlertService tests (~4):**
- `test_bridge_alert_critical_drift` — critical → ALERT severity
- `test_bridge_alert_warning_drift` — warning → ADVISORY severity, routed to medical
- `test_bridge_alert_no_drift` — no drift detected → no alerts
- `test_bridge_alert_dedup` — repeated critical drift → suppressed by cooldown

**Counselor integration tests (~3):**
- `test_counselor_subscribes_drift_event` — event type in subscription list
- `test_counselor_critical_drift_triggers_dm` — critical severity → therapeutic DM sent
- `test_counselor_warning_drift_logs_only` — warning severity → logged, no DM

**VitalsMonitor tests (~2):**
- `test_vitals_includes_drift_metrics` — qualification drift counts in metrics dict
- `test_vitals_no_drift_scheduler` — graceful when `_drift_scheduler` is None

**Config tests (~1):**
- `test_qualification_config_drift_fields` — new fields have correct defaults

### End-to-end milestone test:
```python
async def test_drift_detection_pipeline_e2e():
    """Full pipeline: register tests → run baseline → inject drifted score → detect drift → alert."""
    # 1. Set up store, harness, detector, scheduler with mock emit_event_fn
    # 2. Register a mock test that returns configurable scores
    # 3. Run baseline (score=0.8) + 3 additional runs (score~0.8) to build history
    # 4. Inject drifted run (score=0.3 — far below mean)
    # 5. Run drift analysis
    # 6. Assert: DriftSignal with severity="critical", z_score > 3
    # 7. Assert: QUALIFICATION_DRIFT_DETECTED event emitted
    # 8. Assert: BridgeAlert generated with ALERT severity
```

---

## Scope Boundaries — DO NOT BUILD

- **Tier 2 / Tier 3 tests** — AD-566d / AD-566e. This AD only schedules and analyzes Tier 1.
- **API endpoints** for qualification status — future AD (AD-513 Crew Manifest or standalone).
- **HXI dashboard** for drift visualization — future (AD-566 dashboard extension).
- **LLM model change detection** — the pipeline detects behavioral drift regardless of cause. Correlating drift with LLM model changes (comparing `LLM_HEALTH_CHANGED` events with drift timing) is a future analysis layer.
- **Automatic remediation** — drift triggers alerts, not automatic corrective action. Counselor DMs are therapeutic, not directive. Automated personality recalibration or memory pruning is out of scope.
- **Ship's Records time series export** — longitudinal data is stored in QualificationStore (SQLite). Formal Ship's Records integration (notebook entries, structured reports) is deferred.
- **Dream cycle integration** — running tests as part of the dream cycle (e.g., Step 10) is a valid future optimization. For now, the scheduler runs on its own interval independent of dreams.
- **Federation-wide drift comparison** — comparing drift patterns across ProbOS instances is a federation feature.

---

## Engineering Principles Compliance

- **SOLID (S):** DriftDetector computes statistics. DriftScheduler manages scheduling. BridgeAlertService evaluates thresholds. Each has one responsibility.
- **SOLID (O):** New `check_qualification_drift()` extends BridgeAlertService without modifying existing check methods.
- **SOLID (D):** DriftDetector depends on QualificationStore (abstraction), not SQLite directly. DriftScheduler depends on QualificationHarness protocol.
- **Law of Demeter:** DriftScheduler uses `_drift_scheduler.latest_reports` — no reaching into internal state. VitalsMonitor uses `getattr(rt, "_drift_scheduler", None)` following established pattern.
- **Fail Fast / Log-and-Degrade:** If DriftScheduler fails to start, runtime continues without drift detection (log-and-degrade). If a single agent's drift check fails, log and move to next agent.
- **Cloud-Ready Storage:** All data flows through QualificationStore which uses ConnectionFactory — commercial overlay can swap to Postgres.
- **DRY:** Uses existing `QualificationStore.get_history()` for data retrieval. Uses existing `BridgeAlertService._should_emit()` for dedup. Uses existing `CounselorAgent._send_therapeutic_dm()` for DMs.

Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Files Modified (Expected)

| File | Action | What Changes |
|---|---|---|
| `src/probos/cognitive/drift_detector.py` | **NEW** | DriftSignal, DriftReport, DriftDetector, DriftScheduler |
| `src/probos/config.py` | EDIT | Add drift fields to QualificationConfig |
| `src/probos/events.py` | EDIT | Add QUALIFICATION_DRIFT_DETECTED |
| `src/probos/agents/medical/vitals_monitor.py` | EDIT | Add drift metrics to collect_metrics() |
| `src/probos/bridge_alerts.py` | EDIT | Add check_qualification_drift() |
| `src/probos/cognitive/counselor.py` | EDIT | Subscribe + handle drift event |
| `src/probos/runtime.py` | EDIT | Wire DriftDetector + DriftScheduler |
| `src/probos/startup/shutdown.py` | EDIT | Stop DriftScheduler |
| `tests/test_ad566c_drift_detection.py` | **NEW** | ≥30 tests |
