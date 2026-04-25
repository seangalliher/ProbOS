# AD-566e: Tier 3 Collective Qualification Tests

**Phase:** Era IV — Crew Qualification Battery
**Depends on:** AD-566a (Qualification Harness — COMPLETE), AD-557 (Emergence Metrics — COMPLETE), AD-554 (Convergence Detection — COMPLETE)
**Reuses:** `emergence_metrics.py` (PID engine), `records_store.py` (convergence data), `qualification.py` (harness, protocol, TestResult), `ward_room/` (conversation data)

## Overview

Implement five crew-wide qualification tests (Tier 3) that measure **collective intelligence** — properties that emerge from crew collaboration, not individual agent capability. These tests validate ProbOS's core thesis: *"Architecture is a multiplier orthogonal to model scale."*

**Why this matters:** Tier 1 measures individual cognitive health. Tier 2 measures domain reasoning. Neither captures whether the crew produces better outcomes *together* than agents could individually. Tier 3 closes this gap by measuring coordination value, collective intelligence, and emergent behavior.

**Research grounding:**
- Woolley et al. (Science, 2010): Discovered a general "c-factor" for collective intelligence in human groups. Key predictors: social sensitivity, equal turn-taking, proportion female (maps to personality diversity in AI context). No prior work has measured c-factor for AI agent teams.
- Riedl et al. (arXiv:2510.05174, 2025): PID-based emergence measurement. Synergy × Redundancy interaction predicts group success. ProbOS implementation: AD-557.
- Zhao et al. (arXiv:2603.27539, 2026): Coordination Breakeven Spread — does multi-agent coordination add net value above transaction costs?
- Ge et al. (arXiv:2604.00594, 2026): IRT applied to LLM evaluation. Decomposes observed performance into LLM ability + scaffold ability. Directly measures "architecture multiplier."
- Chen, Zaharia, Zou (arXiv:2307.09009): LLM capability drift makes longitudinal collective measurement essential.

## Design Principles

### Collective vs Individual Tests

Tier 1/2 tests run per-agent: `run(agent_id, runtime) -> TestResult`. Tier 3 tests measure the **crew as a whole**. This creates a protocol mismatch.

**Solution — synthetic crew ID + harness extension:**

1. Tier 3 tests implement the existing `QualificationTest` protocol unchanged. When `run()` is called, they **ignore the `agent_id` parameter** and compute crew-wide metrics from runtime data (Ward Room, emergence engine, convergence data). They return a `TestResult` with `agent_id="__crew__"`.

2. Add a `run_collective(tier, runtime)` method to `QualificationHarness` that runs all tests of a given tier **once** with `agent_id="__crew__"`, rather than per-agent iteration.

3. Update `DriftScheduler._run_cycle()` to call `run_collective(3, runtime)` once per cycle after individual agent tests complete.

This preserves protocol compatibility — Tier 3 tests register the same way, store results the same way (`agent_id="__crew__"`), and compare against baselines the same way. The synthetic `"__crew__"` ID is a convention, not a hack — it represents the collective entity that Tier 3 tests measure.

### Data Sources — Read-Only

Tier 3 tests are **read-only consumers** of existing infrastructure. They do NOT trigger new computations. They read the latest snapshots/results from:
- `EmergenceMetricsEngine.latest_snapshot` — PID synergy, coordination balance, tomeffectiveness
- `RecordsStore` convergence history — convergence events and timing
- `WardRoomService` — thread/post statistics for turn-taking analysis
- Individual Tier 1/2 `TestResult` history — for IRT decomposition

### Thresholds

Collective tests use `threshold = 0.0` (profile measurements, not pass/fail) unless a meaningful minimum exists. The value is in tracking these metrics over time via the drift detection pipeline, not in binary pass/fail judgments.

## Deliverables

### D1: Coordination Breakeven Probe (`CoordinationBreakevenProbe`)

Measures whether multi-agent coordination adds net value above transaction costs.

**Design (adapted from Zhao et al. CBS concept):**

The coordination breakeven question: does the crew produce better outcomes *together* than agents would individually, after accounting for coordination overhead?

**Measurement:**
1. **Coordination value** — read `EmergenceSnapshot.emergence_capacity` (median pairwise synergy). This is the information gained from joint agent contributions that exceeds the sum of individual contributions.
2. **Coordination overhead** — measure from Ward Room statistics: thread count, post count, and convergence time. Higher post counts per thread = more coordination cost. Compute as a normalized ratio.
3. **CBS score** — `coordination_value / (coordination_value + coordination_overhead)`. Range [0, 1]. Score > 0.5 means coordination adds net value.

**Implementation:**

```python
CREW_AGENT_ID = "__crew__"

class CoordinationBreakevenProbe:
    """Coordination Breakeven Spread (AD-566e D1).

    Measures whether multi-agent coordination adds net value above
    transaction costs. Adapted from Zhao et al. (arXiv:2603.27539).
    """

    name = "coordination_breakeven_spread"
    tier = 3
    description = "Does crew coordination add net value above overhead?"
    threshold = 0.0  # Profile measurement
```

**Data access:**
- `runtime._emergence_metrics_engine.latest_snapshot` — read `emergence_capacity` (synergy value). **Private attribute — use underscore prefix.**
- `runtime.ward_room.get_stats()` — read thread/post counts for overhead estimate
- If `latest_snapshot` is None (no emergence data yet), return skip result

**Score computation:**
```python
synergy = snapshot.emergence_capacity
# Overhead proxy: avg posts per multi-agent thread (coordination cost)
stats = await runtime.ward_room.get_stats()
total_posts = stats.get("total_posts", 0)
total_threads = stats.get("total_threads", 1)
avg_posts_per_thread = total_posts / max(total_threads, 1)
# Normalize overhead to [0, 1] — 1 post = no overhead, 20+ posts = max overhead
overhead = min(1.0, max(0.0, (avg_posts_per_thread - 1) / 19.0))
# CBS: synergy / (synergy + overhead), clamped
if synergy + overhead == 0:
    score = 0.5  # Neutral
else:
    score = synergy / (synergy + overhead)
```

**Store in `TestResult.details`:** `{"emergence_capacity": float, "coordination_balance": float, "avg_posts_per_thread": float, "overhead_estimate": float, "cbs_score": float, "threads_analyzed": int, "skipped": bool}`

### D2: IRT Scaffold Decomposition Probe (`ScaffoldDecompositionProbe`)

Separates ProbOS scaffold contribution from raw LLM ability by comparing individual test scores with and without ProbOS infrastructure.

**Design (adapted from Ge et al. IRT concept):**

The architecture multiplier question: how much of an agent's capability comes from ProbOS's scaffold (identity, standing orders, episodic memory, trust network, chain of command) vs the raw LLM?

**Simplified IRT approach (no full IRT parameter estimation — that requires large N):**

Rather than fitting a full IRT model, use a **proxy decomposition**: compare Tier 1 test performance (which tests cognitive capabilities that rely on ProbOS scaffold — personality alignment with seed, episodic recall, confabulation resistance) against a difficulty baseline.

1. **Scaffold-dependent scores** — read the latest Tier 1 results for all agents from `QualificationStore`. Average across all agents and tests. These scores measure capabilities that emerge FROM the scaffold (personality shaped by standing orders, memories from episodic store, etc.).
2. **Baseline LLM performance** — threshold values from Tier 1 test definitions represent "minimum acceptable" performance. The ratio of actual score to threshold indicates scaffold amplification.
3. **Architecture multiplier** — `mean(actual_scores) / mean(thresholds)`. A ratio > 1.0 means the scaffold amplifies capability beyond the bare minimum.

**Implementation:**

```python
class ScaffoldDecompositionProbe:
    """IRT-inspired scaffold decomposition (AD-566e D2).

    Measures how much ProbOS scaffold amplifies agent capability
    beyond raw LLM performance. Adapted from Ge et al.
    (arXiv:2604.00594).
    """

    name = "scaffold_decomposition"
    tier = 3
    description = "Architecture multiplier — scaffold vs raw LLM ability"
    threshold = 0.0  # Profile measurement
```

**Data access:**
- `runtime._qualification_harness.registered_tests` — get Tier 1 test names and thresholds. **Private attribute — use underscore prefix.**
- `runtime._qualification_store.get_history(agent_id, test_name)` — get latest scores per agent per test. **Private attribute — use underscore prefix.**
- Iterate all stored results for Tier 1 tests, compute mean actual vs mean threshold

**Score computation:**
```python
# Gather latest Tier 1 results for all agents
tier1_tests = {name: test for name, test in harness.registered_tests.items() if test.tier == 1 and test.threshold > 0}
actual_scores = []
thresholds = []
for test_name, test in tier1_tests.items():
    history = await store.get_history("__all__")  # Need all agents
    for result in latest_per_agent_test:
        actual_scores.append(result.score)
        thresholds.append(test.threshold)
# Architecture multiplier
if thresholds:
    multiplier = sum(actual_scores) / max(sum(thresholds), 0.01)
    score = min(1.0, multiplier / 2.0)  # Normalize: 2x multiplier = 1.0
else:
    score = 0.5
```

Note: The builder should query the store's `get_latest(agent_id, test_name)` for each *known crew agent* (from the same `_get_crew_agent_ids()` pattern used by DriftScheduler). Only include tests with `threshold > 0` (skip MTI profile which has threshold=0).

**Store in `TestResult.details`:** `{"architecture_multiplier": float, "mean_actual": float, "mean_threshold": float, "agents_measured": int, "tests_measured": int, "per_test_multipliers": dict[str, float], "skipped": bool}`

### D3: Collective Intelligence Factor Probe (`CollectiveIntelligenceProbe`)

Measures Woolley's c-factor adapted for AI agent teams.

**Design (adapted from Woolley et al., Science 2010):**

Woolley found three predictors of collective intelligence in human groups:
1. **Social sensitivity** — ability to read others' mental states (maps to ToM effectiveness)
2. **Equal turn-taking** — variance in speaking time (maps to Ward Room post distribution)
3. **Group diversity** — (maps to personality trait diversity across crew)

**Measurement:**
1. **Turn-taking equality** — compute Gini coefficient of post counts per agent in Ward Room. Lower Gini = more equal = better c-factor. Score: `1 - gini`.
2. **Social sensitivity proxy** — read `EmergenceSnapshot.tom_effectiveness`. This measures whether agents increasingly complement each other over time (coordination awareness).
3. **Diversity** — compute mean pairwise personality distance across crew using `PersonalityTraits.distance_from()`. Higher diversity = more c-factor potential. Normalize to [0, 1] by dividing by `sqrt(5)` (max distance).
4. **c-factor score** — weighted average: turn-taking (0.4) + social sensitivity (0.3) + diversity (0.3). Weights reflect Woolley's finding that turn-taking was the strongest predictor.

**Implementation:**

```python
class CollectiveIntelligenceProbe:
    """Woolley c-factor for AI agent teams (AD-566e D3).

    First known measurement of collective intelligence factor
    for AI agent teams. Adapted from Woolley et al. (Science, 2010).
    """

    name = "collective_intelligence_cfactor"
    tier = 3
    description = "Woolley c-factor — collective intelligence measurement"
    threshold = 0.0  # Profile measurement, novel research
```

**Data access:**
- Ward Room post counts per agent: `runtime.ward_room.get_credibility(agent_id)` → `WardRoomCredibility` with `.total_posts` for each crew agent, OR aggregate from `get_stats()`
- `runtime._emergence_metrics_engine.latest_snapshot` → `tom_effectiveness`. **Private attribute — use underscore prefix.**
- Crew profiles: `load_seed_profile(agent_type)` → seed personality for diversity computation
- Crew agent list: same `_get_crew_agent_ids()` / pool enumeration pattern

**Gini coefficient (pure math, include inline):**
```python
def _gini(values: list[float]) -> float:
    """Gini coefficient. 0 = perfect equality, 1 = perfect inequality."""
    if not values or all(v == 0 for v in values):
        return 0.0
    sorted_v = sorted(values)
    n = len(sorted_v)
    cumsum = sum((2 * (i + 1) - n - 1) * v for i, v in enumerate(sorted_v))
    return cumsum / (n * sum(sorted_v))
```

**Store in `TestResult.details`:** `{"turn_taking_equality": float, "gini_coefficient": float, "tom_effectiveness": float | None, "personality_diversity": float, "agent_count": int, "post_distribution": dict[str, int], "cfactor_score": float, "skipped": bool}`

### D4: Convergence Rate Probe (`ConvergenceRateProbe`)

Measures how quickly the crew reaches cross-agent agreement on shared observations.

**Design (uses AD-554 convergence data):**

Faster convergence (fewer posts/lower elapsed time to reach agreement across departments) indicates better collective reasoning efficiency. Too-fast convergence may indicate groupthink.

**Measurement:**
1. Read convergence events from the system — specifically `ConvergenceDetectedEvent` data stored via the event system, OR check `runtime.records_store` for convergence history.
2. For each detected convergence: compute time from first relevant notebook entry to convergence detection.
3. **Convergence rate** — median time-to-convergence across recent events. Normalize against a reference window (e.g., dream cycle interval).
4. **Quality check** — if convergence coherence is very high (> 0.9) AND convergence time is very short, flag potential groupthink concern.

**Implementation:**

```python
class ConvergenceRateProbe:
    """Convergence rate measurement (AD-566e D4).

    Measures crew's time-to-agreement across departments.
    Consumes AD-554 convergence detection data.
    """

    name = "convergence_rate"
    tier = 3
    description = "Cross-agent convergence speed and quality"
    threshold = 0.0  # Profile measurement
```

**Data access:**
- The convergence detection system (AD-554) runs during proactive notebook writes (`proactive.py:1569–1631`). Results are emitted as events and delivered as Bridge alerts but NOT stored in a queryable history.
- **Pragmatic approach:** Read the latest `EmergenceSnapshot` which contains `threads_analyzed` and `significant_pairs` — these are proxies for how much useful cross-agent interaction is happening. Also check for CONVERGENCE_DETECTED events if an event history is accessible.
- Alternatively, read `runtime.records_store` notebook entries and compute convergence metrics directly using `check_cross_agent_convergence()`.
- If no convergence data is available (cold start, no notebooks yet), return skip result.

**Score computation:**
```python
# Primary metric: fraction of analyzed pairs that show significant coordination
if snapshot.pairs_analyzed > 0:
    coordination_rate = snapshot.significant_pairs / snapshot.pairs_analyzed
else:
    coordination_rate = 0.0

# Secondary: convergence coherence from latest convergence event (if available)
# Combine: score = coordination_rate (already a [0,1] metric)
score = coordination_rate
```

**Store in `TestResult.details`:** `{"pairs_analyzed": int, "significant_pairs": int, "coordination_rate": float, "threads_analyzed": int, "groupthink_risk": bool, "fragmentation_risk": bool, "skipped": bool}`

### D5: Emergence Capacity Probe (`EmergenceCapacityProbe`)

Wraps AD-557 emergence metrics as a qualification test for baseline tracking and drift detection.

**Design (reads AD-557 data directly):**

This is the simplest Tier 3 test — it reads the existing `EmergenceSnapshot` and packages the key metrics as a `TestResult` for longitudinal tracking through the qualification pipeline.

**Measurement:**
1. Read `runtime._emergence_metrics_engine.latest_snapshot`
2. Package: `emergence_capacity`, `coordination_balance`, `synergy_ratio`, `redundancy_ratio`, `hebbian_synergy_correlation`
3. Score: `emergence_capacity` (already [0, 1] range as median synergy)

**Implementation:**

```python
class EmergenceCapacityProbe:
    """Emergence capacity qualification wrapper (AD-566e D5).

    Packages AD-557 PID emergence metrics as a qualification test
    for longitudinal tracking and drift detection.
    """

    name = "emergence_capacity"
    tier = 3
    description = "PID-based emergence capacity (Riedl 2025)"
    threshold = 0.0  # Profile measurement
```

**Data access:**
- `runtime._emergence_metrics_engine` — check `hasattr(runtime, "_emergence_metrics_engine")`
- `.latest_snapshot` — returns `EmergenceSnapshot | None`
- If None, return skip result

**Store in `TestResult.details`:** `{"emergence_capacity": float, "coordination_balance": float, "synergy_ratio": float, "redundancy_ratio": float, "hebbian_synergy_correlation": float | None, "tom_effectiveness": float | None, "groupthink_risk": bool, "fragmentation_risk": bool, "threads_analyzed": int, "pairs_analyzed": int, "skipped": bool}`

### D6: Harness Extension — `run_collective()`

Add a new method to `QualificationHarness` for running collective tests.

**Location:** `src/probos/cognitive/qualification.py`, after `run_all()` (line 467).

```python
async def run_collective(
    self, tier: int, runtime: Any
) -> list[TestResult]:
    """Run all registered tests of a tier once for the crew collective.

    Unlike run_tier() which iterates per-agent, this runs each test
    once with agent_id='__crew__'. Used for Tier 3 collective tests.
    """
    results = []
    for test in self._tests.values():
        if test.tier == tier:
            r = await self.run_test("__crew__", test.name, runtime)
            results.append(r)
    return results
```

Also add a module-level constant:
```python
CREW_AGENT_ID = "__crew__"
```

### D7: DriftScheduler Collective Integration

Update `DriftScheduler._run_cycle()` to run collective tests once per cycle (not per-agent).

**Location:** `src/probos/cognitive/drift_detector.py`, in `_run_cycle()` after the per-agent test loop (around line 300).

Add after the per-agent loop and before `analyze_all_agents()`:

```python
# Run Tier 3 collective tests once (not per-agent)
if 3 in self._drift_tiers:
    try:
        collective_results = await self._harness.run_collective(3, self._runtime)
        # Analyze drift for collective results
        collective_test_names = [r.test_name for r in collective_results]
        if collective_test_names:
            crew_reports = await self._detector.analyze_all_agents(
                ["__crew__"], collective_test_names
            )
            for report in crew_reports:
                self._latest_reports[report.agent_id] = report
                if report.drift_detected:
                    self._emit_drift_events(report)
    except Exception:
        logger.debug("Drift cycle: collective test run failed", exc_info=True)
```

Also update `run_now()` similarly if it has per-agent-only logic.

### D8: Test Registration

Register all five Tier 3 test classes in `runtime.py`, after the Tier 2 registration block.

**Location:** `src/probos/runtime.py`, after the AD-566d Tier 2 registration.

```python
# AD-566e: Register Tier 3 collective tests
from probos.cognitive.collective_tests import (
    CoordinationBreakevenProbe,
    ScaffoldDecompositionProbe,
    CollectiveIntelligenceProbe,
    ConvergenceRateProbe,
    EmergenceCapacityProbe,
)
for test_cls in (
    CoordinationBreakevenProbe,
    ScaffoldDecompositionProbe,
    CollectiveIntelligenceProbe,
    ConvergenceRateProbe,
    EmergenceCapacityProbe,
):
    self._qualification_harness.register_test(test_cls())
```

## File Plan

| File | Action | Content |
|------|--------|---------|
| `src/probos/cognitive/collective_tests.py` | **Create** | D1–D5: Five collective `QualificationTest` implementations + `CREW_AGENT_ID` constant |
| `src/probos/cognitive/qualification.py` | **Modify** | D6: Add `run_collective()` method + `CREW_AGENT_ID` constant |
| `src/probos/cognitive/drift_detector.py` | **Modify** | D7: Add collective test invocation in `_run_cycle()` and `run_now()` |
| `src/probos/runtime.py` | **Modify** | D8: Register Tier 3 tests after Tier 2 block |
| `tests/test_ad566e_collective_tests.py` | **Create** | Tests for all five probes + harness extension + drift integration |

## Infrastructure Available (verified against codebase)

| Component | Location | Access pattern |
|-----------|----------|----------------|
| `QualificationTest` protocol | `cognitive/qualification.py:38` | Implement same protocol, `tier = 3` |
| `TestResult` dataclass | `cognitive/qualification.py:69` | Return from `run()` |
| `QualificationHarness` | `cognitive/qualification.py:349` | Extended with `run_collective()` |
| `QualificationStore.get_latest()` | `cognitive/qualification.py:158` | `async (agent_id, test_name) -> TestResult \| None` |
| `QualificationStore.get_history()` | `cognitive/qualification.py:178` | `async (agent_id, test_name, limit) -> list[TestResult]` |
| `EmergenceMetricsEngine` | `cognitive/emergence_metrics.py:352` | `runtime._emergence_metrics_engine` (private) |
| `EmergenceSnapshot` | `cognitive/emergence_metrics.py:50` | `.emergence_capacity`, `.coordination_balance`, `.synergy_ratio`, `.redundancy_ratio`, `.tom_effectiveness`, `.hebbian_synergy_correlation`, `.groupthink_risk`, `.fragmentation_risk`, `.threads_analyzed`, `.pairs_analyzed`, `.significant_pairs` |
| `RecordsStore.check_cross_agent_convergence()` | `knowledge/records_store.py:405` | `runtime.records_store` (public property) |
| `WardRoomService.get_stats()` | `ward_room/service.py:131` | `runtime.ward_room.get_stats()` — returns dict with counts |
| `WardRoomService.get_credibility()` | `ward_room/service.py:301` | `(agent_id) -> WardRoomCredibility` with `.total_posts` |
| `load_seed_profile()` | `crew_profile.py:401` | `(agent_type) -> dict` — seed personality |
| `PersonalityTraits.distance_from()` | `crew_profile.py:78` | Euclidean distance across Big Five |
| `DriftScheduler._run_cycle()` | `cognitive/drift_detector.py:273` | Add collective invocation |
| `DriftScheduler._get_crew_agent_ids()` | `cognitive/drift_detector.py:364` | Returns `list[str]` of active crew |
| `is_crew_agent()` | `crew_utils.py` | Filter for crew-tier agents |
| `get_department()` | `cognitive/standing_orders.py:63` | Agent-type → department |

**NOT available (do NOT assume):**
- No convergence history store — convergence events are transient (emitted, not persisted). Use emergence snapshot proxies instead.
- No `runtime.qualification_store` public attribute — access via `runtime._qualification_store` (private)
- No `runtime.qualification_harness` public attribute — access via `runtime._qualification_harness` (private)
- No full IRT parameter estimation — use simplified proxy decomposition
- No Woolley replication — adapted c-factor, not literal reproduction

## Test Expectations

**File:** `tests/test_ad566e_collective_tests.py`
**Minimum 35 tests:**

### CoordinationBreakevenProbe tests (5):
1. `test_cbs_probe_protocol_compliance` — verify implements `QualificationTest`, tier == 3
2. `test_cbs_probe_positive_breakeven` — mock high synergy + low overhead → CBS > 0.5
3. `test_cbs_probe_negative_breakeven` — mock low synergy + high overhead → CBS < 0.5
4. `test_cbs_probe_no_emergence_data_skipped` — no snapshot available → skip result
5. `test_cbs_probe_details_structure` — verify all detail fields present

### ScaffoldDecompositionProbe tests (5):
6. `test_scaffold_probe_protocol_compliance` — verify implements `QualificationTest`, tier == 3
7. `test_scaffold_probe_positive_multiplier` — mock Tier 1 scores > thresholds → multiplier > 1.0
8. `test_scaffold_probe_no_amplification` — mock Tier 1 scores == thresholds → multiplier ~1.0
9. `test_scaffold_probe_no_tier1_data_skipped` — no stored results → skip result
10. `test_scaffold_probe_details_structure` — verify `architecture_multiplier`, `per_test_multipliers`

### CollectiveIntelligenceProbe tests (6):
11. `test_cfactor_probe_protocol_compliance` — verify implements `QualificationTest`, tier == 3
12. `test_cfactor_probe_equal_participation` — mock equal post counts → high turn-taking score
13. `test_cfactor_probe_skewed_participation` — mock one agent dominates → low turn-taking score
14. `test_cfactor_probe_diverse_personalities` — mock diverse seed profiles → high diversity score
15. `test_cfactor_probe_no_data_skipped` — no ward room data → skip result
16. `test_cfactor_probe_details_structure` — verify `gini_coefficient`, `turn_taking_equality`, `personality_diversity`

### ConvergenceRateProbe tests (5):
17. `test_convergence_probe_protocol_compliance` — verify implements `QualificationTest`, tier == 3
18. `test_convergence_probe_high_coordination` — mock many significant pairs → high score
19. `test_convergence_probe_low_coordination` — mock few significant pairs → low score
20. `test_convergence_probe_no_data_skipped` — no snapshot → skip result
21. `test_convergence_probe_details_structure` — verify `pairs_analyzed`, `significant_pairs`, `coordination_rate`

### EmergenceCapacityProbe tests (5):
22. `test_emergence_probe_protocol_compliance` — verify implements `QualificationTest`, tier == 3
23. `test_emergence_probe_reads_snapshot` — mock snapshot with known values → score == emergence_capacity
24. `test_emergence_probe_groupthink_flagged` — mock groupthink_risk=True → included in details
25. `test_emergence_probe_no_data_skipped` — no engine or no snapshot → skip result
26. `test_emergence_probe_details_structure` — verify all emergence fields in details

### Harness extension tests (4):
27. `test_run_collective_executes_tier3` — `run_collective(3, runtime)` runs all 5 Tier 3 tests
28. `test_run_collective_skips_other_tiers` — `run_collective(3, runtime)` does NOT run Tier 1/2 tests
29. `test_run_collective_uses_crew_agent_id` — all results have `agent_id == "__crew__"`
30. `test_crew_agent_id_constant` — verify `CREW_AGENT_ID == "__crew__"`

### Registration tests (2):
31. `test_harness_registers_all_tier3_tests` — all 5 tests registered, all have `tier == 3`
32. `test_harness_run_collective_returns_5` — `run_collective(3, runtime)` returns 5 results

### DriftScheduler collective integration tests (3):
33. `test_drift_scheduler_runs_collective_when_tier3_enabled` — with `drift_check_tiers=[1,2,3]`, collective tests run once per cycle
34. `test_drift_scheduler_skips_collective_when_tier3_disabled` — with `drift_check_tiers=[1,2]`, no collective invocation
35. `test_drift_scheduler_collective_drift_emitted` — collective results with drift → `QUALIFICATION_DRIFT_DETECTED` event

## Scope Boundaries — Do NOT Build

- **Do NOT trigger new emergence computations** — read existing `latest_snapshot` only
- **Do NOT trigger new convergence checks** — read existing data only
- **Do NOT implement full IRT parameter estimation** — use simplified proxy decomposition
- **Do NOT implement literal Woolley replication** — adapted c-factor for AI context
- **Do NOT implement S_macro, I_3, or G_3** — deferred to AD-557c (higher-order PID)
- **Do NOT add API endpoints** — defer to future AD
- **Do NOT modify VitalsMonitor** — already monitors qualification drift from AD-566c
- **Do NOT modify Counselor** — already subscribes to `QUALIFICATION_DRIFT_DETECTED` from AD-566c
- **Do NOT modify BridgeAlertService** — already handles qualification drift from AD-566c
- **Do NOT modify the `QualificationTest` protocol** — keep it unchanged, use convention (`__crew__` ID)
- **Do NOT store convergence history** — that's future infrastructure. Use snapshot proxies.

## Acceptance Criteria

1. All 5 test classes implement `QualificationTest` protocol (verified by `isinstance` check).
2. All 5 tests have `tier = 3`.
3. All 5 tests return `agent_id = "__crew__"` (or `CREW_AGENT_ID` constant).
4. All 5 tests registered with harness at startup via `runtime.py`.
5. `QualificationHarness.run_collective(tier, runtime)` method added and works correctly.
6. `DriftScheduler._run_cycle()` calls `run_collective(3, runtime)` once when Tier 3 is in configured tiers.
7. All tests handle missing data gracefully (skip, don't fail).
8. No LLM calls needed — all tests are read-only consumers of existing metrics.
9. Gini coefficient computed correctly (inline helper function).
10. Minimum 35 tests, all passing.
11. Regression: existing AD-566a/b/c/d tests still pass.
12. Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.
