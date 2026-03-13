# Phase 20 — Emergent Behavior Detection

## Context

You are building Phase 20 of ProbOS, a probabilistic agent-native OS runtime. Read `PROGRESS.md` for full architectural context. Current state: **1358/1358 tests passing + 11 skipped. Latest AD: AD-235.**

ProbOS has spent 19 phases building a complete learning infrastructure — trust (Bayesian Beta distributions), Hebbian routing (connection weights between intents and agents), episodic memory (ChromaDB semantic store), dreaming (offline consolidation), feedback loops (human signals to trust/Hebbian/episodic), and correction detection. The system **learns** but does not **notice**. It accumulates patterns but nothing watches for unexpected emergent behavior — cooperation clusters, trust anomalies, routing shifts, or consolidation anomalies.

The Noöplex paper (§6, in `Vibes/Nooplex_Final.md`) defines four measurable emergence criteria:

1. **Cross-domain synthesis** — outputs from multiple agent domains that require integration
2. **Integrated information (TC_N)** — total correlation measuring how much the system exceeds the sum of its parts
3. **Novel coordination patterns** — coordination strategies that differ from initial protocols
4. **Cumulative capability growth** — capability expansion accelerating with experience

This phase implements practical detectors for these criteria adapted to ProbOS's single-mesh scale.

### The Noöplex TC_N metric

From §6: `TC_N = H(Y) − Σᵢ H(Yᵢ | Y₋ᵢ)` where Y is the system-level output distribution and Yᵢ is the contribution of mesh Mᵢ. For ProbOS (single mesh, multiple agent pools), we adapt this: **pools are the partition units** instead of meshes. TC_N > 0 indicates that agent pools cooperate in ways that produce outcomes no single pool could achieve — multi-step DAGs where pool results depend on each other.

---

## Pre-Build Audit

Before writing any code, verify:

1. **Latest AD number in PROGRESS.md** — confirm AD-235 is the latest. Phase 20 AD numbers start at **AD-236**. If AD-235 is NOT the latest, adjust all AD numbers in this prompt upward accordingly.
2. **Test count** — confirm 1358 tests pass before starting: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
3. **Read these files thoroughly:**
   - `src/probos/mesh/routing.py` — understand `HebbianRouter`, `_weights` dict (keyed by `(source, target, rel_type)` tuples), `all_weights_typed()`, `REL_INTENT`, `REL_AGENT`, `weight_count`, `decay_all()`. These weights are the primary data source for cooperation cluster detection
   - `src/probos/consensus/trust.py` — understand `TrustNetwork`, `TrustRecord` (alpha, beta, score, observations, uncertainty), `_records` dict, `all_scores()`, `raw_scores()`, `get_record()`. Trust trajectories are the data source for change-point detection
   - `src/probos/cognitive/dreaming.py` — understand `DreamingEngine.dream_cycle()`, `DreamReport` type (episodes_replayed, weights_strengthened, weights_pruned, trust_adjustments, pre_warm_intents, duration_ms), `DreamScheduler`. Dream reports are the data source for consolidation anomaly detection
   - `src/probos/cognitive/behavioral_monitor.py` — understand `BehavioralMonitor` (tracks *self-created* agents only). The new `EmergentDetector` monitors the *entire* agent population and is architecturally distinct
   - `src/probos/agents/introspect.py` — understand the IntrospectionAgent pattern: `intent_descriptors`, `_handled_intents`, `handle_intent()` dispatching to handler methods, `_runtime` reference for data access. New intents will be added here
   - `src/probos/types.py` — understand `DreamReport`, `IntentDescriptor`, existing dataclass patterns
   - `src/probos/runtime.py` — understand `start()` initialization sequence, `status()` dict, `_dream_scheduler`, where other subsystem refs are stored. The EmergentDetector will be wired here
   - `src/probos/experience/shell.py` — understand command registration pattern (COMMANDS dict, handler methods)
   - `src/probos/experience/panels.py` — understand rendering pattern (pure functions taking data, returning Rich Panel/Table)
   - `src/probos/substrate/event_log.py` — understand `EventLog.log()` API (category, event, detail strings)
   - `src/probos/cognitive/llm_client.py` — understand `MockLLMClient` regex patterns — you'll need to add patterns for new introspection intents

---

## What To Build

### Step 1: EmergentDetector Core Module (AD-236)

**File:** `src/probos/cognitive/emergent_detector.py` (new)

**AD-236: `EmergentDetector` — continuous analysis of system dynamics for emergent behavior patterns.** This is a pure analysis module. It reads from existing data sources (Hebbian weights, trust records, dream reports, episodic memory) and produces structured analysis results. It never mutates system state.

```python
@dataclass
class EmergentPattern:
    """A detected emergent behavior pattern."""
    pattern_type: str       # "cooperation_cluster", "trust_anomaly",
                            # "routing_shift", "consolidation_anomaly",
                            # "capability_growth"
    description: str        # Human-readable description
    confidence: float       # 0.0-1.0
    evidence: dict          # Supporting data
    timestamp: float        # time.monotonic() when detected
    severity: str           # "info", "notable", "significant"


@dataclass
class SystemDynamicsSnapshot:
    """Point-in-time snapshot of system-level metrics."""
    timestamp: float
    tc_n: float                              # Total correlation proxy
    cooperation_clusters: list[dict]         # Agent groups that co-succeed
    trust_distribution: dict                 # mean, std, min, max, skew
    routing_entropy: float                   # How evenly intents are distributed
    capability_count: int                    # Number of distinct intent types handled
    dream_consolidation_rate: float          # Weights changed per dream cycle


class EmergentDetector:
    """Monitors system dynamics for emergent behavior patterns.

    Unlike BehavioralMonitor (which tracks individual self-created agents),
    EmergentDetector analyzes population-level patterns across ALL agents:
    - Hebbian weight topology → cooperation clusters
    - Trust score trajectories → change-point detection
    - Routing patterns → intent distribution shifts
    - Dream consolidation → unusual strengthening/pruning
    - Capability growth → rate of new intent types
    """
```

**Constructor:**
```python
def __init__(
    self,
    hebbian_router: HebbianRouter,
    trust_network: TrustNetwork,
    max_history: int = 100,
) -> None:
```

The detector stores a bounded history of `SystemDynamicsSnapshot` entries (ring buffer, max 100) for trend analysis. It does NOT run a background loop — it is called explicitly (by the runtime after dream cycles, and by introspection intents on demand).

**Methods to implement:**

#### `analyze() -> list[EmergentPattern]`

The main analysis entry point. Runs all detectors and returns any detected patterns. Call sequence:

1. Take a `SystemDynamicsSnapshot` (calls all metric methods below)
2. Store in history ring buffer
3. Run each detector against the snapshot + history
4. Return all detected patterns

#### `compute_tc_n() -> float`

**Adapted TC_N for single-mesh ProbOS.** The Noöplex's TC_N measures information integration across meshes. ProbOS has one mesh with multiple agent pools. Adapt:

- **Partition**: each agent pool is a "partition unit"
- **Signal**: for each recent episode, record which pools contributed (which agent types handled nodes in the DAG)
- **Metric**: compute the fraction of successful DAGs that required **multi-pool cooperation** (2+ distinct pools contributing to the same DAG). This is a proxy for "the system produces outcomes no single pool could achieve"
- **Formula**: `tc_n = multi_pool_dag_count / total_dag_count` over the last N episodes
- **Interpretation**: tc_n ≈ 0.0 means the system operates as independent pools (no integration). tc_n ≈ 1.0 means every task requires cooperation across pools (high integration)

This is a practical proxy, not a formal information-theoretic computation. The Noöplex paper explicitly endorses proxy metrics (§6, "proxy metrics derived from observable cross-mesh information flow") for practical implementations.

**Data source:** Episodic memory. Each episode records `agent_ids` and `dag_summary`. Parse agent IDs to extract agent types (from the deterministic ID format `{type}_{pool}_{index}_{hash}`), map to pool names, count unique pools per episode.

#### `detect_cooperation_clusters() -> list[dict]`

Analyze the Hebbian weight graph for **agent cooperation clusters** — groups of agents/intents that frequently co-succeed.

- Read all weights from `hebbian_router.all_weights_typed()` where `rel_type == "intent"`
- Build an adjacency representation: which intents share agents (co-occur in the same DAGs)
- Find connected components above a weight threshold (e.g., 0.1)
- Return clusters as `[{"intents": [...], "agents": [...], "avg_weight": float, "size": int}]`

**Keep it simple.** Use a threshold-based connected components algorithm, not spectral clustering or community detection. Iterate over weights, group by shared source or target, merge overlapping sets. This is O(E) where E is the number of weights — fine for ProbOS's scale (typically < 100 weights).

#### `detect_trust_anomalies() -> list[EmergentPattern]`

Detect agents whose trust trajectory deviates significantly from the population.

- Get all trust records via `trust_network.raw_scores()`
- Compute population statistics: mean trust score, standard deviation
- Flag agents whose trust score is > 2 standard deviations from the mean (either direction)
- Flag agents with unusually high observation counts relative to the population (hyperactive agents)
- Compare against previous snapshot (if available) to detect **change points**: agents whose trust moved by > 0.15 since the last analysis

Return `EmergentPattern` with `pattern_type="trust_anomaly"`.

#### `detect_routing_shifts() -> list[EmergentPattern]`

Detect when an agent or pool starts handling intent types it has never handled before.

- Read Hebbian weights typed, focusing on `rel_type == "intent"`
- Compare current intent→agent mappings against previous snapshot
- Flag new connections that didn't exist before (an agent handling a brand-new intent type)
- Compute **routing entropy**: `-Σ p(pool) · log(p(pool))` where p(pool) is the fraction of total Hebbian weight going to each pool. Higher entropy = more evenly distributed routing. A sudden drop in entropy means routing is concentrating on fewer pools

Return `EmergentPattern` with `pattern_type="routing_shift"`.

#### `detect_consolidation_anomalies(dream_report: DreamReport | None) -> list[EmergentPattern]`

When a dream report is available, check for unusual patterns:

- If `weights_strengthened` or `weights_pruned` exceed 2x the historical average (from snapshot history), flag as anomaly
- If `trust_adjustments` is unusually high, flag
- If `pre_warm_intents` contains intents that don't match any registered handler, flag (predicting intents that don't exist yet — could indicate the system is anticipating capability gaps)

Return `EmergentPattern` with `pattern_type="consolidation_anomaly"`.

#### `compute_routing_entropy() -> float`

Compute Shannon entropy over the Hebbian weight distribution across pools:

```python
# Get all intent->agent weights
weights = self._router.all_weights_typed()
intent_weights = {k: v for k, v in weights.items() if k[2] == REL_INTENT}

# Sum weights by target agent pool (extract pool from agent ID)
pool_totals: dict[str, float] = {}
for (source, target, _), weight in intent_weights.items():
    pool = self._extract_pool(target)  # parse from deterministic ID
    pool_totals[pool] = pool_totals.get(pool, 0.0) + weight

# Compute entropy
total = sum(pool_totals.values())
if total == 0:
    return 0.0
entropy = 0.0
for w in pool_totals.values():
    p = w / total
    if p > 0:
        entropy -= p * math.log2(p)
return entropy
```

#### `get_snapshot() -> SystemDynamicsSnapshot`

Assemble a current snapshot from all metrics. Called by `analyze()` and by the introspection agent directly.

#### `summary() -> dict`

Return a JSON-serializable summary of the current state for `/anomalies` command and `status()` integration:

```python
{
    "tc_n": float,
    "routing_entropy": float,
    "cooperation_clusters": int,  # count
    "trust_anomalies": int,       # count
    "routing_shifts": int,        # count
    "consolidation_anomalies": int,  # count
    "snapshots_recorded": int,
    "patterns_detected": int,     # total historical
    "latest_patterns": [...]      # last 5 EmergentPattern as dicts
}
```

**Run tests after this step: all 1358 existing tests must still pass (no existing code modified).**

---

### Step 2: Wire EmergentDetector into Runtime (AD-237)

**File:** `src/probos/runtime.py`

**AD-237: EmergentDetector runtime integration.** Wire the detector into the runtime lifecycle:

1. **Construction:** Create `EmergentDetector` in `start()` after Hebbian router and trust network are initialized. Pass `hebbian_router` and `trust_network` references. Also pass `episodic_memory` reference for TC_N computation.

2. **Post-dream analysis:** After each dream cycle completes (find where `DreamScheduler` callback triggers or where dream reports are stored), call `self._emergent_detector.analyze()` and pass the dream report for consolidation anomaly detection. This piggybacks on existing dream cycle timing — no new background loop.

3. **Event logging:** When patterns are detected, log them to `event_log` with category `"emergent"` and event names matching pattern types (e.g., `"cooperation_cluster"`, `"trust_anomaly"`, `"routing_shift"`, `"consolidation_anomaly"`).

4. **Status integration:** Add `"emergent"` key to `status()` dict with the detector's `summary()` output.

5. **Store detector reference:** `self._emergent_detector = EmergentDetector(...)` so introspection agent and shell can access it.

**Important:** The detector is created unconditionally (doesn't require a config flag). It's a pure observer with negligible overhead. If episodic memory is not available, `compute_tc_n()` returns 0.0 gracefully.

**Run tests after this step: all 1358 must still pass. Add NO new tests yet — wiring only.**

---

### Step 3: Introspection Agent Integration (AD-238)

**File:** `src/probos/agents/introspect.py`

**AD-238: Two new introspection intents for emergent behavior.** Add to `IntrospectionAgent`:

1. **`system_anomalies`** — returns currently detected anomalies and patterns.
   - Intent descriptor: `IntentDescriptor(name="system_anomalies", params={}, description="Report detected system anomalies — trust outliers, routing shifts, consolidation anomalies, cooperation clusters", requires_reflect=True)`
   - Handler calls `rt._emergent_detector.analyze()` to run fresh analysis, returns detected patterns as structured data
   - If no detector available (shouldn't happen, but guard), return graceful "Emergent detection not available"

2. **`emergent_patterns`** — returns system dynamics overview including TC_N, routing entropy, cooperation clusters, and trend data.
   - Intent descriptor: `IntentDescriptor(name="emergent_patterns", params={}, description="Report emergent behavior metrics — cooperation clusters, total correlation (TC_N), routing entropy, capability growth trends", requires_reflect=True)`
   - Handler calls `rt._emergent_detector.get_snapshot()` and `rt._emergent_detector.summary()` to return the full dynamics picture
   - Include snapshot history trend (tc_n values over time, routing entropy over time) if available

Add both to `intent_descriptors`, `_handled_intents`, and the `act()` dispatcher.

**MockLLMClient patterns:** Add patterns for `system_anomalies` and `emergent_patterns` in `llm_client.py`. These should return simple DAGs routing to the introspect agent, matching the existing pattern for `introspect_memory` and `introspect_system`.

**Run tests after this step: all 1358 must still pass.**

---

### Step 4: Shell Command and Panel Rendering (AD-239)

**File:** `src/probos/experience/shell.py`, `src/probos/experience/panels.py`

**AD-239: `/anomalies` shell command and `render_anomalies_panel()`.** Follow the existing panel pattern.

**`render_anomalies_panel(summary: dict, patterns: list[dict]) -> Panel`** in `panels.py`:

- Top section: system dynamics metrics (TC_N, routing entropy, cluster count, snapshot count)
- Bottom section: Rich Table of detected patterns (type, description, confidence, severity, age)
- Empty state: "No anomalous patterns detected — system operating normally"
- Severity color coding: `info` = dim, `notable` = yellow, `significant` = red

**`/anomalies` command** in `shell.py`:

- Calls `self.runtime._emergent_detector.analyze()` to get fresh patterns
- Calls `self.runtime._emergent_detector.summary()` for metrics
- Renders via `render_anomalies_panel()`
- If detector not available, prints "Emergent detection not available"
- Add to COMMANDS dict and `/help` output

**Run tests after this step: all 1358 must still pass.**

---

### Step 5: Tests (AD-240)

**File:** `tests/test_emergent_detector.py` (new)

**AD-240: Comprehensive test suite for EmergentDetector.** Target: ~45 tests.

#### EmergentPattern and SystemDynamicsSnapshot dataclasses (3 tests)
- EmergentPattern fields roundtrip (1 test)
- SystemDynamicsSnapshot fields roundtrip (1 test)
- EmergentPattern severity values (1 test)

#### TC_N computation (6 tests)
- No episodes → tc_n = 0.0 (1 test)
- All single-pool DAGs → tc_n = 0.0 (1 test)
- All multi-pool DAGs → tc_n = 1.0 (1 test)
- Mixed single and multi-pool → tc_n between 0 and 1 (1 test)
- Pool extraction from deterministic agent IDs (1 test)
- Handles missing/malformed agent_ids gracefully (1 test)

#### Cooperation cluster detection (5 tests)
- Empty weights → no clusters (1 test)
- Single strong connection → one cluster (1 test)
- Two disconnected groups → two clusters (1 test)
- Weights below threshold filtered out (1 test)
- Cluster contains expected agents and intents (1 test)

#### Trust anomaly detection (6 tests)
- All agents similar trust → no anomalies (1 test)
- One agent very low trust → anomaly detected (1 test)
- One agent very high trust → anomaly detected (1 test)
- Change point: agent trust moved > 0.15 since last snapshot (1 test)
- Hyperactive agent: high observation count relative to population (1 test)
- Single agent in network → no anomaly (insufficient population) (1 test)

#### Routing shift detection (5 tests)
- No previous snapshot → no shifts (first analysis) (1 test)
- New intent→agent connection appears → routing shift detected (1 test)
- Stable routing → no shifts (1 test)
- Entropy computation: uniform distribution → high entropy (1 test)
- Entropy computation: concentrated distribution → low entropy (1 test)

#### Consolidation anomaly detection (5 tests)
- No dream report → no anomalies (1 test)
- Normal dream report → no anomalies (1 test)
- High weights_strengthened (>2x avg) → anomaly (1 test)
- High weights_pruned (>2x avg) → anomaly (1 test)
- Pre-warm intents with no matching handler → flagged (1 test)

#### analyze() integration (4 tests)
- analyze() returns list of EmergentPattern (1 test)
- analyze() stores snapshot in history (1 test)
- History ring buffer respects max_history (1 test)
- Multiple analyze() calls build trend data (1 test)

#### summary() and get_snapshot() (3 tests)
- summary() returns JSON-serializable dict (1 test)
- get_snapshot() returns SystemDynamicsSnapshot (1 test)
- summary() latest_patterns capped at 5 (1 test)

#### Runtime integration (4 tests)
- Runtime creates EmergentDetector at start (1 test)
- status() includes emergent key (1 test)
- EmergentDetector without episodic memory → tc_n = 0.0 (1 test)
- Post-dream analysis wired (mock dream, verify analyze called) (1 test)

#### Introspection integration (4 tests)
- system_anomalies intent returns detected patterns (1 test)
- emergent_patterns intent returns dynamics snapshot (1 test)
- MockLLMClient routes "are there any anomalies" to system_anomalies (1 test)
- MockLLMClient routes "show emergent patterns" to emergent_patterns (1 test)

#### Shell and panel (5 tests)
- /anomalies command renders panel (1 test)
- /help includes /anomalies (1 test)
- render_anomalies_panel with patterns shows table (1 test)
- render_anomalies_panel empty shows "operating normally" (1 test)
- render_anomalies_panel severity color coding (1 test)

**Total: ~50 tests → ~1408 total**

---

## What NOT To Build

- **No perception gateways or proactive agents** — detection is pulled (on demand / post-dream), not pushed
- **No self-directed goal generation** — detected anomalies are surfaced to the user, not auto-acted upon
- **No policy engine changes** — anomalies are informational, not governance-enforced
- **No knowledge graph** — analysis uses existing data stores (Hebbian weights, trust network, episodic memory)
- **No changes to the dream cycle itself** — the detector reads dream reports, it doesn't modify dreaming behavior
- **No new background loop** — analysis piggybacks on dream cycle timing and on-demand introspection
- **No changes to existing BehavioralMonitor** — that monitors individual self-created agents; this monitors population-level dynamics. They are complementary, not overlapping
- **No formal information-theoretic TC_N** — use the proxy metric approach explicitly endorsed by the Noöplex paper
- **No federation-specific detection** — single-mesh only; federation emergence detection is a future phase
- **No UI/HXI work** — shell command only; HXI rendering is deferred

---

## Implementation Order

1. **Step 1 — EmergentDetector module** (new file, no existing code changes) → run tests
2. **Step 2 — Runtime wiring** (runtime.py changes only) → run tests
3. **Step 3 — Introspection agent** (introspect.py + llm_client.py) → run tests
4. **Step 4 — Shell + panels** (shell.py + panels.py) → run tests
5. **Step 5 — Tests** (new test file) → run tests, verify all pass

**After each step, run the full test suite: `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`**

If tests fail at any step, fix before proceeding. Do NOT skip failing tests.

---

## PROGRESS.md Update

After all tests pass, update PROGRESS.md:

1. **Line 2** — Update status line: `Phase 20 — Emergent Behavior Detection (XXXX/XXXX tests + 11 skipped)` with actual test count
2. **What's Been Built section** — Add EmergentDetector under Cognitive Layer table
3. **What's Working section** — Add Phase 20 test summary
4. **Architectural Decisions** — Add entries for AD-236 through AD-240
5. **Checklist** — Mark "Emergent Behavior Detection" as complete with strikethrough
6. **Test count** — Update the test count in the "What's Working" narrative

**AD numbering reminder: Current highest is AD-235. This phase uses AD-236 through AD-240. Verify before committing.**
