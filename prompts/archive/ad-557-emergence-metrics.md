# AD-557: Emergence Metrics — Information-Theoretic Collaborative Intelligence Measurement

**Priority:** Medium-High
**Prerequisites:** Ward Room (Phase 33) — COMPLETE, EpisodicMemory — COMPLETE, VitalsMonitor — COMPLETE, TrustNetwork — COMPLETE, AD-531 (Episode Clustering / embeddings) — COMPLETE
**Related:** AD-559 (Provenance Tracking, planned — will enrich synergy scores with independence ground truth), AD-554 (Convergence Detection, planned — not built, basic scoring included here), AD-506b (Peer Repetition Detection — complementary signal)
**Research:** `docs/research/emergent-coordination-research.md` (Riedl 2025, arXiv:2510.05174v3)

## Context

ProbOS claims "architecture is a multiplier orthogonal to model scale" and that sovereign agents with structured context produce "qualitatively different collaborative output." We have anecdotal evidence (iatrogenic trust diagnosis, confabulation cascade, CMO Day One) but no quantitative measurement.

Riedl (2025) provides the information-theoretic framework: Partial Information Decomposition (PID) decomposes joint mutual information into Unique, Redundancy, and Synergy components. Their key finding: **Synergy x Redundancy interaction predicts group success** (beta=0.24, p=0.014). Neither alone works. Redundancy amplifies synergy by 27%.

ProbOS has everything Riedl's experiment uses (personality via Big Five, ToM via standing order) plus things they don't (episodic memory, trust evolution, departmental structure, chain of command). AD-557 measures whether these produce measurable emergence.

**Scope note:** This AD builds the measurement infrastructure and core metrics. The HXI dashboard (roadmap sub-feature 5) is deferred to a follow-up AD. AD-559 (Provenance Tracking) will later enrich these metrics with independence ground truth — design the API to accommodate future provenance scores without refactoring.

## Existing State

**EmergentDetector (`cognitive/emergent_detector.py`):**
- Detects cooperation clusters (Union-Find on Hebbian graph), trust anomalies (sigma deviation), routing shifts, consolidation anomalies
- `tc_n` = coarse integration proxy (fraction of multi-pool routes)
- Ring buffer of 100 `SystemDynamicsSnapshot`s with trend regression
- **No PID computation, no Ward Room thread analysis, no pairwise synergy**

**Embedding infrastructure (`knowledge/embeddings.py`):**
- `embed_text(text)` — ChromaDB ONNX embeddings (keyword fallback)
- `compute_similarity(text_a, text_b)` — cosine similarity
- Already used by AD-531 episode clustering

**Ward Room (`ward_room/models.py`, `ward_room/service.py`):**
- `WardRoomThread`: id, channel_id, author_id, title, body, thread_mode, created_at
- `WardRoomPost`: id, thread_id, author_id, body, created_at
- `browse_threads(agent_id, channels, limit, since)` — retrieves threads with metadata
- `get_thread(thread_id)` — returns thread with posts
- Already used by dream Step 7e (observational learning)

**ToM Standing Order (Federation Constitution, `config/standing_orders/federation.md`):**
- Already in place: "Before contributing to a shared task or discussion, consider what other agents are likely contributing..."
- Four sub-points: think about others' perspectives, complement don't echo, department shapes your lens, adapt in context

**Dream cycle:** Steps 0 through 8 (gap detection). Step 9 is available.

**DreamReport (`types.py`):** Dataclass with existing fields for cluster counts, procedure counts, gap predictions. Needs new emergence fields.

## What to Build

Five parts. New module: `src/probos/cognitive/emergence_metrics.py`. Dream integration as Step 9. API endpoint for cached metrics. VitalsMonitor integration for alerting.

---

### Part 0: Configuration (`config.py`)

Add `EmergenceMetricsConfig` dataclass:

```python
@dataclass
class EmergenceMetricsConfig:
    """Configuration for emergence metrics computation (AD-557)."""
    # PID computation
    pid_bins: int = 2  # K=2 quantile binning (per Riedl 2025)
    pid_permutation_shuffles: int = 50  # Significance testing (Riedl uses 200, we use fewer for performance)
    pid_significance_threshold: float = 0.05  # p-value threshold for significant emergence

    # Thread analysis
    min_thread_contributors: int = 2  # Minimum agents in thread to analyze
    min_thread_posts: int = 3  # Minimum posts in thread to analyze
    thread_lookback_hours: float = 24.0  # How far back to look for threads during dream

    # Coordination balance
    groupthink_redundancy_threshold: float = 0.8  # Flag when redundancy dominates
    fragmentation_synergy_threshold: float = 0.1  # Flag when synergy is near zero

    # ToM effectiveness
    tom_baseline_window: int = 20  # Number of initial threads to establish baseline
    tom_trend_min_samples: int = 10  # Minimum threads before computing trend

    # Hebbian correlation
    hebbian_synergy_min_interactions: int = 5  # Minimum Hebbian interactions to correlate
```

Add `emergence_metrics` field to the main config, defaulting to `EmergenceMetricsConfig()`.

---

### Part 1: PID Computation Engine (`cognitive/emergence_metrics.py`)

**Pure Python implementation — no numpy dependency.** Follow the pattern of `EmergentDetector._linear_regression()` which implements stats without external deps.

#### 1a: Data structures

```python
@dataclass
class PIDResult:
    """Partial Information Decomposition result for an agent pair."""
    agent_i: str
    agent_j: str
    unique_i: float  # Information unique to agent i
    unique_j: float  # Information unique to agent j
    redundancy: float  # Shared/overlapping information
    synergy: float  # Information only available from combination
    total_mi: float  # Total mutual information
    n_contributions: int  # Number of contributions analyzed
    p_value: float  # Significance via permutation test
    is_significant: bool  # p_value < threshold

@dataclass
class EmergenceSnapshot:
    """Ship-level emergence metrics at a point in time."""
    timestamp: float
    emergence_capacity: float  # Median pairwise synergy across all pairs
    coordination_balance: float  # Synergy x Redundancy interaction score
    redundancy_ratio: float  # Mean redundancy / (redundancy + synergy)
    synergy_ratio: float  # Mean synergy / (redundancy + synergy)
    threads_analyzed: int
    pairs_analyzed: int
    significant_pairs: int  # Pairs with p < threshold
    top_synergy_pairs: list  # Top 5 (agent_i, agent_j, synergy) tuples
    per_department: dict  # department_name -> {synergy, redundancy, balance}
    groupthink_risk: bool  # redundancy_ratio > threshold
    fragmentation_risk: bool  # synergy_ratio < threshold
    tom_effectiveness: float | None  # Trend slope of complementarity over time (None if insufficient data)
    hebbian_synergy_correlation: float | None  # Correlation between Hebbian weight and synergy

    # Future enrichment point for AD-559
    provenance_independence: float | None  # Will be populated by AD-559
```

#### 1b: Williams-Beer I_min Implementation

The PID computation pipeline:

1. **Extract contribution vectors:** For each thread, get the sequence of posts. For each agent pair (i, j) that both contributed, extract their contribution embeddings using `embed_text()`.

2. **Construct the "outcome" variable:** The thread's collective output. Use the embedding of the concatenated thread body (or the final synthesis post if identifiable). This is the target variable Y.

3. **Discretize:** Quantile-bin each agent's contribution embedding similarity-to-outcome into K=2 bins (above/below median). This gives binary variables X_i, X_j, Y.

4. **Compute mutual information:** For binary variables, MI can be computed from the 2x2 contingency table:
   ```
   MI(X; Y) = sum over x,y of P(x,y) * log2(P(x,y) / (P(x) * P(y)))
   ```

5. **Compute I_min (Williams-Beer redundancy):**
   ```
   I_min(Y; X_i, X_j) = sum over y of min(I_spec(X_i; Y=y), I_spec(X_j; Y=y))
   ```
   where `I_spec(X; Y=y) = sum over x of P(x|y) * log2(P(x|y) / P(x))` (specific information).

6. **Decompose:**
   ```
   Redundancy = I_min
   Unique_i = MI(X_i; Y) - I_min
   Unique_j = MI(X_j; Y) - I_min
   Synergy = MI(X_i, X_j; Y) - MI(X_i; Y) - MI(X_j; Y) + I_min
   ```
   where `MI(X_i, X_j; Y)` is the joint mutual information.

7. **Permutation significance test:** Shuffle agent labels B times (default 50, Riedl uses 200). Compute synergy for each shuffle. p-value = fraction of shuffled synergies >= observed synergy.

**Implementation notes:**
- Handle log(0) by using `max(p, 1e-10)` before log
- All probabilities estimated from frequency counts
- Contributions are pooled across multiple threads for each agent pair (more data = more reliable estimates)
- If an agent pair has fewer contributions than `min_thread_posts`, skip that pair

#### 1c: Complementarity Score (for ToM effectiveness)

For consecutive contributions in a Ward Room thread:
```python
def compute_complementarity(posts: list[WardRoomPost]) -> float:
    """Semantic dissimilarity between consecutive contributions by different agents.

    Higher = more complementary (agents adding new information).
    Lower = more redundant (agents echoing each other).
    """
    # For each consecutive pair of posts by different agents:
    #   similarity = compute_similarity(post_a.body, post_b.body)
    #   complementarity = 1.0 - similarity
    # Return mean complementarity
```

Track complementarity over time. Trend slope = ToM effectiveness measure.

---

### Part 2: Thread Analysis Pipeline (`cognitive/emergence_metrics.py`)

```python
class EmergenceMetricsEngine:
    """Computes information-theoretic emergence metrics from Ward Room conversations."""

    def __init__(self, config: EmergenceMetricsConfig):
        self._config = config
        self._snapshots: deque[EmergenceSnapshot] = deque(maxlen=100)
        self._complementarity_history: list[tuple[float, float]] = []  # (timestamp, score) for ToM trend
        self._baseline_established: bool = False
        self._baseline_complementarity: float | None = None

    async def compute_emergence_metrics(
        self,
        ward_room: WardRoomService,
        trust_network: TrustNetwork,
        hebbian_router,  # routing.HebbianRouter or similar
        get_department: Callable[[str], str | None] | None = None,
    ) -> EmergenceSnapshot:
        """Full emergence metrics computation. Called during dream Step 9."""
```

Pipeline:
1. **Retrieve recent threads:** `ward_room.browse_threads()` with `since` = now minus `thread_lookback_hours`. Filter to threads with >= `min_thread_contributors` unique authors and >= `min_thread_posts` posts.

2. **Extract agent contributions:** For each qualifying thread, for each agent pair, collect their contributions as embedded vectors.

3. **Compute pairwise PID:** For each agent pair with sufficient data, compute `PIDResult`. Collect all pairs.

4. **Aggregate ship-level metrics:**
   - `emergence_capacity` = median synergy across all significant pairs (0.0 if no significant pairs)
   - `coordination_balance` = mean(synergy * redundancy) across pairs (the interaction term from Riedl)
   - `redundancy_ratio`, `synergy_ratio` = normalized proportions
   - `top_synergy_pairs` = top 5 by synergy value

5. **Per-department metrics:** If `get_department` is provided, group pairs by department match:
   - Intra-department pairs (same dept) — expect higher redundancy
   - Cross-department pairs (different depts) — expect higher synergy
   - Per-department aggregates

6. **ToM effectiveness:** Compute complementarity for each thread. Append to history. If history length >= `tom_trend_min_samples`, compute linear regression slope. Positive slope = ToM standing order is working. Use the same `_linear_regression` approach as EmergentDetector (copy the method or extract a shared utility if one exists).

7. **Hebbian-synergy correlation:** For agent pairs with both Hebbian weight data and PID results, compute Pearson correlation. High Hebbian + low synergy = echo pattern flag.

8. **Risk flags:**
   - `groupthink_risk` = `redundancy_ratio > groupthink_redundancy_threshold`
   - `fragmentation_risk` = `synergy_ratio < fragmentation_synergy_threshold`

9. **Create and store `EmergenceSnapshot`.** Append to ring buffer.

---

### Part 3: Dream Cycle Integration (`dreaming.py`)

Add **Step 9: Emergence Metrics** after Step 8 (gap detection):

```python
# Step 9: Emergence metrics (AD-557)
if self._emergence_metrics_engine and self._ward_room:
    try:
        snapshot = await self._emergence_metrics_engine.compute_emergence_metrics(
            ward_room=self._ward_room,
            trust_network=self.trust_network,
            hebbian_router=self._hebbian_router,
            get_department=self._get_department,
        )
        report.emergence_capacity = snapshot.emergence_capacity
        report.coordination_balance = snapshot.coordination_balance
        report.groupthink_risk = snapshot.groupthink_risk
        report.fragmentation_risk = snapshot.fragmentation_risk
        report.tom_effectiveness = snapshot.tom_effectiveness
        self._log("step-9", f"Emergence: capacity={snapshot.emergence_capacity:.3f}, "
                  f"balance={snapshot.coordination_balance:.3f}, "
                  f"pairs={snapshot.pairs_analyzed} ({snapshot.significant_pairs} significant)")
    except Exception as e:
        self._log("step-9", f"Emergence metrics failed: {e}")
```

**DreamingEngine constructor:** Add optional `emergence_metrics_engine: EmergenceMetricsEngine | None = None` parameter. Wire during startup.

**DreamReport extension (`types.py`):** Add fields:
```python
# AD-557: Emergence metrics
emergence_capacity: float | None = None
coordination_balance: float | None = None
groupthink_risk: bool = False
fragmentation_risk: bool = False
tom_effectiveness: float | None = None
```

---

### Part 4: Event Emission & Alerting

**New event types (`events.py`):**
```python
EMERGENCE_METRICS_UPDATED = "emergence_metrics_updated"
GROUPTHINK_WARNING = "groupthink_warning"
FRAGMENTATION_WARNING = "fragmentation_warning"
```

**Emission:** After computing the snapshot in Step 9:
- Always emit `EMERGENCE_METRICS_UPDATED` with the snapshot data
- If `groupthink_risk` is True: emit `GROUPTHINK_WARNING`
- If `fragmentation_risk` is True: emit `FRAGMENTATION_WARNING`

**Counselor subscription (`counselor.py`):**
Add subscriptions to `GROUPTHINK_WARNING` and `FRAGMENTATION_WARNING`:
```python
# In _setup_event_subscriptions():
self._subscribe(EventType.GROUPTHINK_WARNING, self._on_groupthink_warning)
self._subscribe(EventType.FRAGMENTATION_WARNING, self._on_fragmentation_warning)
```

Handlers: Log the risk, run targeted assessment on the most redundant/isolated agents, issue therapeutic DM if warranted. Rate-limit: one per dream cycle (the events already fire once per dream, so this is naturally rate-limited).

**Bridge alerts:** If `BridgeAlertService` monitors emergence events, surface them as ADVISORY-level alerts. Follow the existing `_check_trust_anomalies()` pattern. This is optional — only if it fits naturally. Do NOT force-wire if the integration is complex.

---

### Part 5: API Endpoint & Telemetry

**API endpoint (`routers/` — find appropriate router):**

```python
@router.get("/emergence")
async def get_emergence_metrics():
    """Return cached emergence metrics from last dream cycle."""
    # Return the latest EmergenceSnapshot from the engine's ring buffer
    # Include: emergence_capacity, coordination_balance, risk flags,
    #          top synergy pairs, per-department breakdown, ToM trend
```

Also add a history endpoint:
```python
@router.get("/emergence/history")
async def get_emergence_history(limit: int = 20):
    """Return emergence metrics time series."""
    # Return the last N EmergenceSnapshots from the ring buffer
```

**VitalsMonitor integration:** Add emergence metrics to the vitals collection if the EmergenceMetricsEngine is available:
```python
# In VitalsMonitor.collect_metrics() or equivalent:
# Read cached emergence_capacity and coordination_balance from the engine
# Include in vitals output alongside trust_mean, pool_health, etc.
```

This is READ-ONLY from VitalsMonitor — it displays the cached values from the last dream cycle, it does NOT recompute.

---

### Part 6: Runtime Wiring

In the appropriate startup module (check where DreamingEngine is constructed):

```python
# Create EmergenceMetricsEngine
emergence_engine = EmergenceMetricsEngine(config.emergence_metrics)

# Wire into DreamingEngine
dreaming_engine = DreamingEngine(
    ...,
    emergence_metrics_engine=emergence_engine,
)

# Wire department lookup (same as AD-558)
# If AD-558 is already built, reuse the same lookup function
```

If AD-558 hasn't been built yet when this is implemented, add the department lookup wiring. If AD-558 is already built, reuse the `get_department` function that AD-558 wired into TrustNetwork.

---

## Deferred

- **AD-557b — HXI Emergence Dashboard (roadmap sub-feature 5):** Frontend visualization. Ship-level Emergence Capacity time series, Coordination Balance heatmap, top synergistic pairs, convergence quality distribution. Separate AD once backend metrics are stable.
- **AD-559 enrichment:** The `provenance_independence` field on `EmergenceSnapshot` is reserved but always None until AD-559 is built. Design is forward-compatible.
- **AD-557c — Higher-Order Emergence Measures (S_macro, I_3, G_3):** Riedl defines higher-order measures (3-agent interactions, triplet information). These require substantially more data and computation. Defer until pairwise PID proves valuable.
- **AD-554 — Convergence Detection Enhancement (roadmap sub-feature 4):** AD-554 is not built. Basic convergence quality scoring is included in the PID results (significant synergy = genuine convergence). Full convergence detection is a separate AD.

---

## Tests

### File: `tests/test_emergence_metrics.py` (~40-45 tests)

**PID computation (pure math):**
1. Two identical contributions produce high redundancy, low synergy
2. Two complementary contributions produce high synergy, low redundancy
3. Completely independent contributions produce high unique, low redundancy
4. Synergy + Redundancy + Unique_i + Unique_j = Total MI (decomposition identity)
5. PID with empty contributions returns zero
6. PID with single contribution per agent works
7. Quantile binning with K=2 produces binary discretization
8. Permutation significance test: random data produces p > 0.05 (not significant)
9. Permutation significance test: structured data produces p < 0.05 (significant)
10. Log(0) handled gracefully (no NaN/Inf)

**Thread analysis:**
11. Thread with < min_contributors is skipped
12. Thread with < min_posts is skipped
13. Thread within lookback window is included
14. Thread outside lookback window is excluded
15. Multiple threads pooled for same agent pair
16. Cross-department pairs identified correctly
17. Intra-department pairs identified correctly
18. Department lookup fallback (None) skips department analysis

**Ship-level aggregation:**
19. emergence_capacity = median pairwise synergy
20. coordination_balance = mean(synergy * redundancy)
21. redundancy_ratio + synergy_ratio = 1.0 (when both > 0)
22. top_synergy_pairs returns top 5 sorted by synergy
23. No significant pairs produces emergence_capacity = 0.0
24. Per-department breakdown computed correctly

**Risk detection:**
25. High redundancy_ratio flags groupthink_risk
26. Low synergy_ratio flags fragmentation_risk
27. Balanced ratio flags neither risk
28. GROUPTHINK_WARNING event emitted when risk detected
29. FRAGMENTATION_WARNING event emitted when risk detected

**ToM effectiveness:**
30. Complementarity score: identical posts → 0.0
31. Complementarity score: unrelated posts → high
32. Complementarity tracked over time
33. Linear regression slope computed after min_samples
34. Positive slope indicates ToM is working
35. Insufficient data returns None (not 0.0)

**Hebbian correlation:**
36. High Hebbian weight + high synergy → positive correlation
37. High Hebbian weight + low synergy → negative correlation (echo flag)
38. Insufficient interactions returns None
39. Correlation computed only for pairs with both data sources

**Dream integration:**
40. Step 9 runs after Step 8
41. DreamReport fields populated from snapshot
42. Step 9 failure does not crash dream cycle (log-and-degrade)
43. Engine not wired → Step 9 skipped gracefully

**API & telemetry:**
44. /emergence returns latest snapshot
45. /emergence/history returns time series
46. VitalsMonitor includes cached emergence values

**Snapshot ring buffer:**
47. Snapshots stored up to maxlen
48. Old snapshots evicted when buffer full

---

## Implementation Notes

1. **Pure Python PID.** Do NOT import numpy, scipy, or any external math library. Implement MI, I_min, and permutation test using builtins + `math.log2()`. Follow the pattern of `EmergentDetector._linear_regression()`.

2. **Embedding cost.** Each `embed_text()` call has compute cost. Cache embeddings for posts within the dream cycle. Do not re-embed the same post body twice. A simple `{post_id: embedding}` dict within the computation scope is sufficient.

3. **Permutation count.** Riedl uses B=200 shuffles. Default to 50 for performance (dream cycles have time budgets). Make configurable. Even B=50 gives reasonable significance estimates for K=2 binary variables.

4. **Thread retrieval.** Reuse the proven pattern from dream Step 7e (observational learning): `ward_room.browse_threads()` with `since` filter. Do NOT invent a new retrieval mechanism.

5. **ToM baseline bootstrapping.** The ToM standing order is already active. The first `tom_baseline_window` threads analyzed establish the baseline complementarity. This means early snapshots may show `tom_effectiveness = None` until enough data accumulates. This is correct behavior — report it as "baseline collecting" in logs.

6. **Fail-safe.** Step 9 must be wrapped in try/except. Emergence metrics are observational — a failure must NEVER crash the dream cycle. Log and continue. Follow the pattern of Steps 7e (observational learning) and Step 8 (gap detection).

7. **Forward compatibility with AD-559.** The `provenance_independence` field on `EmergenceSnapshot` is always `None` for now. When AD-559 is built, it will provide per-convergence independence scores that enrich the synergy interpretation. Do NOT add provenance logic to AD-557.

8. **Counselor response to risk flags.** Keep it simple: log the risk, optionally send a therapeutic DM to the most redundant agent pair (for groupthink) or the most isolated agent (for fragmentation). Do NOT implement complex intervention logic — that's future work.

9. **Linear regression utility.** Check if `EmergentDetector._linear_regression()` can be extracted to a shared utility in `cognitive/` (e.g., `cognitive/math_utils.py`). If it's simple to extract, do so. If not, copy the implementation. Do NOT refactor EmergentDetector in this AD.

10. **The coordination_balance metric** is not just `synergy * redundancy` averaged. Per Riedl, it's the interaction term: groups succeed when they have BOTH synergy AND redundancy. Pure synergy without redundancy is fragile (no shared ground). Pure redundancy without synergy is groupthink. The product captures the interaction.

## Acceptance Criteria

- [ ] PID computation produces correct decomposition (identity holds: S + R + U_i + U_j = MI)
- [ ] Ward Room threads analyzed during dream Step 9
- [ ] EmergenceSnapshot computed and stored in ring buffer
- [ ] Groupthink and fragmentation risks detected and flagged
- [ ] ToM effectiveness trend computed from complementarity history
- [ ] Hebbian-synergy correlation computed for agent pairs
- [ ] Events emitted (EMERGENCE_METRICS_UPDATED, risk warnings)
- [ ] Counselor subscribes to risk warning events
- [ ] API endpoints return cached metrics and history
- [ ] DreamReport extended with emergence fields
- [ ] All ~45 tests pass
- [ ] Dream cycle regression passes (Steps 0-8 unaffected)
- [ ] Zero external math dependencies (pure Python)
- [ ] Step 9 failure does not crash dream cycle
