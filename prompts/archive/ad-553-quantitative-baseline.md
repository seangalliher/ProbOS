# Build Prompt: AD-553 — Quantitative Baseline Auto-Capture

**Ticket:** AD-553
**Priority:** Medium (knowledge enrichment pipeline, step 4 of 7)
**Scope:** Auto-attach system metrics to notebook entries, baseline comparison on update, VitalsMonitor integration
**Principles Compliance:** DRY (reuse VitalsMonitor data), Fail Fast (log-and-degrade), Law of Demeter (access VitalsMonitor via runtime registry), Single Responsibility (metric collection in one function)
**Dependencies:** AD-550 (Notebook Dedup — COMPLETE), AD-551 (Notebook Consolidation — COMPLETE), AD-552 (Self-Repetition Detection — COMPLETE), AD-514 (VitalsMonitor public API — COMPLETE), AD-557 (Emergence Metrics — COMPLETE)

---

## Context

Agents write notebook entries about their observations, but these entries lack quantitative context. When Chapel notes "trust patterns seem unstable" or LaForge writes "system performance degraded," there's no concrete data attached. Later, when reading these entries, neither the agent nor the crew can tell *how* unstable trust was or *what* the actual metrics were at the time of writing.

AD-553 solves this by auto-attaching a standardized metrics snapshot to every notebook write, and computing metric deltas when an existing entry is updated. This transforms notebooks from purely qualitative records into quantitative-qualitative observations — each entry captures *what the agent thought* alongside *what the system looked like*.

**Key insight:** VitalsMonitor already collects all the metrics we need (`latest_vitals` property). The notebook frontmatter already supports arbitrary YAML keys. We just need to bridge the two.

---

## Architecture

### Metric Snapshot

A standalone function `collect_notebook_metrics(runtime) -> dict[str, Any]` collects a standardized metrics snapshot from the runtime. It reads from VitalsMonitor's `latest_vitals` cache (no I/O, no async needed) and supplements with trust data.

**Metrics captured** (all optional — graceful degradation if unavailable):

| Metric | Source | Type |
|--------|--------|------|
| `trust_mean` | VitalsMonitor `latest_vitals` | float |
| `trust_min` | VitalsMonitor `latest_vitals` | float |
| `system_health` | VitalsMonitor `latest_vitals` | float |
| `pool_health_mean` | VitalsMonitor `latest_vitals["pool_health"]` | float (mean of all pools) |
| `emergence_capacity` | VitalsMonitor `latest_vitals` | float or None |
| `coordination_balance` | VitalsMonitor `latest_vitals` | float or None |
| `llm_health` | VitalsMonitor `latest_vitals["llm_health"]["overall"]` | str ("operational"/"degraded"/"offline"/"unknown") |
| `agent_trust` | `rt.trust_network.get_score(agent_id)` | float |
| `active_agents` | `len(rt.registry.all())` | int |

The metrics dict is flat (no nesting). Values are rounded to 3 decimal places for readability. `None` values are omitted from the dict rather than stored as null.

### Where Metrics Are Stored

In the notebook entry's **YAML frontmatter** under a `metrics` key:

```yaml
---
author: Chapel
classification: department
status: draft
created: '2026-04-03T12:00:00+00:00'
updated: '2026-04-03T14:00:00+00:00'
revision: 2
department: medical
topic: trust-pattern-analysis
tags:
- trust-pattern-analysis
metrics:
  trust_mean: 0.723
  trust_min: 0.412
  system_health: 0.891
  pool_health_mean: 0.875
  agent_trust: 0.756
  active_agents: 42
  llm_health: operational
---
```

This is clean, queryable, and survives AD-551 dream consolidation (which preserves frontmatter through `write_entry()`).

### Baseline Delta on Update

When a notebook entry is being *updated* (dedup gate returns `action == "update"`), the existing entry's frontmatter contains the previous `metrics` dict. AD-553 computes a delta and appends it as a `metrics_delta` key in the new frontmatter:

```yaml
metrics:
  trust_mean: 0.723
  trust_min: 0.412
  system_health: 0.891
metrics_delta:
  trust_mean: -0.041
  trust_min: +0.085
  system_health: +0.012
```

Only numeric metrics that changed by more than 0.01 are included in the delta. String metrics (like `llm_health`) show as `"operational → degraded"` if changed.

### Integration Points

1. **`proactive.py` notebook write path** (line 1424): After the dedup gate passes and before `write_notebook()` is called, collect metrics and pass them to `write_notebook()` via a new `metrics` parameter.

2. **`records_store.py` `write_notebook()`**: Accept optional `metrics` dict, forward to `write_entry()`.

3. **`records_store.py` `write_entry()`**: Accept optional `metrics` dict, merge into frontmatter.

4. **VitalsMonitor access**: Find VitalsMonitor via `rt.registry.all()` — iterate to find agent with `agent_type == "vitals_monitor"`. Cache the reference after first lookup for efficiency (store as `self._vitals_monitor` on the ProactiveExecutor).

---

## Deliverables

### Deliverable 1: Metric Collection Function

**File:** `src/probos/proactive.py`

Add a module-level function (NOT a method — keeps it testable without instantiating ProactiveExecutor):

```python
def collect_notebook_metrics(runtime: Any, agent_id: str = "") -> dict[str, Any]:
    """AD-553: Collect standardized metrics snapshot for notebook attachment.

    Returns flat dict of metric_name -> value. Degrades gracefully:
    returns empty dict if runtime/VitalsMonitor unavailable.
    """
    metrics: dict[str, Any] = {}
    if runtime is None:
        return metrics

    # VitalsMonitor cached data (no I/O)
    vitals = None
    try:
        for agent in runtime.registry.all():
            if getattr(agent, 'agent_type', '') == 'vitals_monitor':
                vitals = agent.latest_vitals
                break
    except Exception:
        pass  # Registry unavailable

    if vitals:
        for key in ("trust_mean", "trust_min", "system_health"):
            val = vitals.get(key)
            if val is not None:
                metrics[key] = round(val, 3)

        # Pool health mean
        pool_health = vitals.get("pool_health")
        if pool_health and isinstance(pool_health, dict):
            vals = [v for v in pool_health.values() if isinstance(v, (int, float))]
            if vals:
                metrics["pool_health_mean"] = round(sum(vals) / len(vals), 3)

        # Emergence (AD-557)
        for key in ("emergence_capacity", "coordination_balance"):
            val = vitals.get(key)
            if val is not None:
                metrics[key] = round(val, 3)

        # LLM health
        llm = vitals.get("llm_health")
        if isinstance(llm, dict):
            overall = llm.get("overall")
            if overall:
                metrics["llm_health"] = overall

    # Agent's own trust score
    if agent_id and hasattr(runtime, 'trust_network') and runtime.trust_network:
        try:
            score = runtime.trust_network.get_score(agent_id)
            if score is not None:
                metrics["agent_trust"] = round(score, 3)
        except Exception:
            pass

    # Active agent count
    try:
        metrics["active_agents"] = len(runtime.registry.all())
    except Exception:
        pass

    return metrics
```

### Deliverable 2: Baseline Delta Computation

**File:** `src/probos/proactive.py`

Add a function to compute delta between old and new metrics:

```python
def compute_metrics_delta(
    old_metrics: dict[str, Any],
    new_metrics: dict[str, Any],
    *,
    min_numeric_delta: float = 0.01,
) -> dict[str, Any]:
    """AD-553: Compute delta between two metrics snapshots.

    Returns dict of metric_name -> delta for numeric values that changed
    by more than min_numeric_delta, and "old → new" strings for changed
    string values. Returns empty dict if no meaningful changes.
    """
    delta: dict[str, Any] = {}
    all_keys = set(old_metrics) | set(new_metrics)

    for key in sorted(all_keys):
        old_val = old_metrics.get(key)
        new_val = new_metrics.get(key)

        if old_val is None or new_val is None:
            continue  # Skip if either side is missing

        if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
            diff = new_val - old_val
            if abs(diff) >= min_numeric_delta:
                delta[key] = round(diff, 3)
        elif isinstance(old_val, str) and isinstance(new_val, str):
            if old_val != new_val:
                delta[key] = f"{old_val} → {new_val}"

    return delta
```

### Deliverable 3: RecordsStore Integration

**File:** `src/probos/knowledge/records_store.py`

**3a.** Add `metrics` parameter to `write_notebook()`:

```python
async def write_notebook(
    self,
    callsign: str,
    topic_slug: str,
    content: str,
    *,
    department: str = "",
    tags: list[str] | None = None,
    classification: str = "department",
    metrics: dict[str, Any] | None = None,  # AD-553
) -> str:
```

Forward `metrics` to `write_entry()`.

**3b.** Add `metrics` parameter to `write_entry()`:

```python
async def write_entry(
    self,
    author: str,
    path: str,
    content: str,
    message: str,
    *,
    classification: str = "ship",
    status: str = "draft",
    department: str = "",
    topic: str = "",
    tags: list[str] | None = None,
    metrics: dict[str, Any] | None = None,  # AD-553
) -> str:
```

After building the frontmatter dict (line 117), before composing the full document (line 141):

```python
# AD-553: Attach metrics snapshot
if metrics:
    frontmatter["metrics"] = metrics
```

**3c.** Return previous metrics in `check_notebook_similarity()` result dict:

Add `"existing_metrics"` to the return dict when an existing entry is found. Extract from frontmatter:

```python
_existing_metrics = fm.get("metrics", {})
```

Include in all return paths where the exact match is found (the `{...}` dicts at lines 308-317, 319-329, 332-341):

```python
"existing_metrics": _existing_metrics,
```

And in the no-match default:

```python
"existing_metrics": {},
```

### Deliverable 4: Proactive Write Path Integration

**File:** `src/probos/proactive.py`

In the notebook write path (after the AD-552 frequency check passes, before the `write_notebook()` call at line 1424):

```python
# AD-553: Collect metrics snapshot and compute delta
_nb_metrics: dict[str, Any] = {}
_nb_metrics_delta: dict[str, Any] = {}
_metric_capture_enabled = True
if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'records'):
    _metric_capture_enabled = getattr(
        self._runtime.config.records, 'notebook_metrics_enabled', True
    )

if _metric_capture_enabled:
    try:
        _nb_metrics = collect_notebook_metrics(self._runtime, agent.id)
        # Baseline delta: compare with previous metrics if updating
        if dedup_result.get("action") == "update":
            _old_metrics = dedup_result.get("existing_metrics", {})
            if _old_metrics and _nb_metrics:
                _nb_metrics_delta = compute_metrics_delta(_old_metrics, _nb_metrics)
                if _nb_metrics_delta:
                    _nb_metrics["metrics_delta"] = _nb_metrics_delta
    except Exception:
        logger.debug("AD-553: Metric collection failed for %s/%s", callsign, topic_slug, exc_info=True)
```

Then pass `_nb_metrics` to the write call:

```python
await self._runtime._records_store.write_notebook(
    callsign=callsign,
    topic_slug=topic_slug,
    content=notebook_content,
    department=department,
    tags=[topic_slug],
    metrics=_nb_metrics if _nb_metrics else None,  # AD-553
)
```

**Important:** The `metrics_delta` is stored *inside* the `metrics` dict in frontmatter (as a nested key). This keeps the frontmatter structure simple — one `metrics` key with the snapshot plus an optional `metrics_delta` sub-key showing what changed.

### Deliverable 5: Config Knob

**File:** `src/probos/config.py`

Add to `RecordsConfig` (after the AD-552 settings, line 397):

```python
# AD-553: Notebook metric capture
notebook_metrics_enabled: bool = True
```

A single toggle is sufficient. The metric set is fixed by the collection function — no need for per-metric config.

---

## Files Modified (Expected)

| File | Change |
|------|--------|
| `src/probos/proactive.py` | `collect_notebook_metrics()`, `compute_metrics_delta()`, write path integration |
| `src/probos/knowledge/records_store.py` | `metrics` param on `write_entry()` + `write_notebook()`, `existing_metrics` in dedup result |
| `src/probos/config.py` | `RecordsConfig.notebook_metrics_enabled` |
| `tests/test_ad553_quantitative_baseline.py` | New test file |

---

## Prior Work to Absorb

| Source | What to Reuse | How |
|--------|---------------|-----|
| VitalsMonitor `latest_vitals` | Cached metrics dict with trust_mean, trust_min, pool_health, system_health, emergence_capacity, coordination_balance, llm_health | Read-only access via `agent.latest_vitals` — no async needed |
| VitalsMonitor `collect_metrics()` | Shows exactly what metrics are available and their structure | Template for which fields to extract |
| AD-550 `check_notebook_similarity()` | Already returns `revision`, `created_iso`, `updated_iso` in result dict | Extend to also return `existing_metrics` from frontmatter |
| AD-550 `write_entry()` | Frontmatter builder — arbitrary YAML dict keys supported | Add `metrics` key to frontmatter dict — no structural change |
| AD-551 `write_notebook()` | Delegates to `write_entry()` with keyword args | Add `metrics` kwarg passthrough |
| AD-552 dedup gate (proactive.py 1357-1422) | Already reads dedup_result fields | Add `existing_metrics` read after dedup check |
| `_parse_document()` (records_store.py 573-583) | Returns full frontmatter dict including any `metrics` key | Delta computation reads old metrics from this |
| TrustNetwork `get_score()` | Per-agent trust score | Use for `agent_trust` metric |

---

## Tests (25 minimum)

### TestCollectNotebookMetrics (8 tests)

1. Returns empty dict when runtime is None
2. Returns empty dict when no VitalsMonitor in registry
3. Returns correct metrics when VitalsMonitor has `latest_vitals` (trust_mean, trust_min, system_health)
4. Computes `pool_health_mean` as average of pool health values
5. Includes `emergence_capacity` and `coordination_balance` when present in vitals
6. Includes `llm_health` string from vitals
7. Includes `agent_trust` from trust_network when agent_id provided
8. Includes `active_agents` count from registry
9. Omits metrics with None values (no nulls in output)
10. All float values rounded to 3 decimal places

### TestComputeMetricsDelta (5 tests)

11. Returns empty dict when no meaningful changes (all deltas < 0.01)
12. Returns numeric deltas for values that changed by >= 0.01
13. Returns "old → new" string for changed string values (e.g., llm_health)
14. Omits keys present in only one side (old or new)
15. Respects custom `min_numeric_delta` parameter

### TestWritePathIntegration (5 tests)

16. Metrics snapshot attached to frontmatter on new notebook write
17. Metrics snapshot + delta attached on notebook update (action="update")
18. No metrics attached when `notebook_metrics_enabled=False`
19. Metric collection failure does not block notebook write (log-and-degrade)
20. `existing_metrics` returned in dedup result when entry has metrics in frontmatter

### TestRecordsStoreMetrics (3 tests)

21. `write_entry()` includes `metrics` key in frontmatter when provided
22. `write_notebook()` passes `metrics` through to `write_entry()`
23. `check_notebook_similarity()` returns `existing_metrics` from frontmatter

### TestFrontmatterPersistence (2 tests)

24. Metrics survive write → read cycle (frontmatter `metrics` key preserved)
25. Metrics delta stored inside `metrics` dict under `metrics_delta` key

---

## Validation Checklist

- [ ] `collect_notebook_metrics()` works with full runtime (all metrics populated)
- [ ] `collect_notebook_metrics()` degrades gracefully (empty dict) when VitalsMonitor absent
- [ ] `compute_metrics_delta()` filters insignificant changes (<0.01)
- [ ] Metrics attached as `metrics` key in YAML frontmatter
- [ ] Delta attached as `metrics.metrics_delta` nested key when updating
- [ ] `existing_metrics` returned by `check_notebook_similarity()` for baseline comparison
- [ ] `write_entry()` and `write_notebook()` accept optional `metrics` parameter
- [ ] Config toggle `notebook_metrics_enabled` controls metric capture
- [ ] Metric capture failure does NOT block notebook write
- [ ] No new async calls — VitalsMonitor `latest_vitals` is a sync property
- [ ] All existing AD-550/551/552 tests still pass (0 regressions)
- [ ] Float values rounded to 3 decimal places
- [ ] None values omitted rather than stored as null
- [ ] No new dependencies — uses only existing runtime services

---

## Notes

- **No async for metric collection.** VitalsMonitor's `latest_vitals` is a sync `@property` that returns the last cached snapshot from the sliding window. No I/O, no await. This is deliberate — notebook writes should not block on metric collection.
- **Metrics capture is universal.** Every notebook write gets a metrics snapshot, not just "baseline" entries. The roadmap originally said "baseline/metrics-tagged" but universal capture is simpler and more valuable — it provides temporal context for ANY observation.
- **Delta is in frontmatter, not content body.** Storing the delta in the content body would pollute the agent's narrative. Frontmatter is metadata — the agent's written content stays clean.
- **One config knob.** The metric set is deterministic (whatever VitalsMonitor has). No per-metric toggles needed. If you don't want metrics, flip `notebook_metrics_enabled=False`.
- **Dream consolidation compatibility.** AD-551's Step 7g calls `write_entry()` for consolidated entries. Metrics in frontmatter will be preserved through consolidation. The consolidated entry's metrics reflect the last write before consolidation — this is correct (the consolidation itself doesn't change system state).
- **VitalsMonitor lookup is cached.** The first call iterates `rt.registry.all()` to find the vitals_monitor agent. Subsequent calls can reuse the reference. However, for simplicity in v1, the lookup happens in `collect_notebook_metrics()` each call — the registry iteration is cheap (O(n) over ~55 agents) and avoids stale references.
