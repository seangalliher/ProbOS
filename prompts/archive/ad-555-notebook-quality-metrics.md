# Build Prompt: AD-555 — Notebook Quality Metrics & Dashboarding

**Ticket:** AD-555
**Priority:** Medium (knowledge enrichment pipeline, step 6 of 7)
**Scope:** Quality metrics aggregation engine, per-agent quality scoring, API endpoints, Bridge alerts, VitalsMonitor integration, HXI quality panel
**Principles Compliance:** DRY (reuse list_entries/get_stats, follow EmergenceMetricsEngine pattern), Fail Fast (log-and-degrade), Law of Demeter (access RecordsStore via runtime), Single Responsibility (quality engine is one class, one concern)
**Dependencies:** AD-550 (dedup — COMPLETE), AD-551 (consolidation — COMPLETE), AD-552 (self-repetition — COMPLETE), AD-553 (quantitative baseline — COMPLETE), AD-554 (real-time convergence — COMPLETE), AD-557 (emergence metrics engine pattern — COMPLETE)

---

## Context

The Notebook Quality Pipeline (AD-550–554) built five layers of smart behavior — dedup gates, dream consolidation, self-repetition detection, quantitative baselines, and cross-agent convergence/divergence detection. Each layer produces data: dedup actions, revision counts, novelty scores, repetition events, convergence clusters, metrics snapshots.

But none of this data is aggregated. The Captain can't answer "which agents produce high-signal notebooks?" or "what's the fleet's notebook signal-to-noise ratio?" The Counselor can't answer "is Chapel stuck in a repetition loop on trust analysis?" Individual events fire, but there's no longitudinal quality picture.

AD-555 creates that picture. A `NotebookQualityEngine` (following the EmergenceMetricsEngine pattern from AD-557) aggregates quality data from RecordsStore, produces per-agent and system-wide quality snapshots, surfaces them via API endpoints, integrates with VitalsMonitor for ship health visibility, and triggers Bridge alerts when quality degrades.

**Key insight:** Almost all the data already exists — it's in notebook frontmatter (revisions, metrics, timestamps), event emissions (repetition, convergence), and RecordsStore methods (list_entries, get_stats). AD-555 is primarily an *aggregation and visibility* layer, not new detection logic.

---

## Architecture

### Quality Snapshot Model

Two levels of quality data:

**Per-Agent Quality (`AgentNotebookQuality` dataclass):**

| Metric | Type | Source |
|--------|------|--------|
| `callsign` | str | author from frontmatter |
| `department` | str | department from frontmatter |
| `total_entries` | int | count of entries for this author |
| `unique_topics` | int | count of distinct topic values |
| `entries_per_topic_avg` | float | total_entries / unique_topics |
| `entries_per_topic_max` | int | max entries for any single topic |
| `mean_revision` | float | average revision count across entries |
| `max_revision` | int | highest revision count |
| `novel_content_rate` | float | fraction of entries with revision == 1 (first write, not updates to existing) |
| `stale_rate` | float | fraction of entries not updated within `staleness_hours` |
| `convergence_contributions` | int | times this agent appeared in convergence events |
| `repetition_alerts` | int | times repetition was detected for this agent |
| `quality_score` | float | composite 0.0–1.0 (see formula below) |

**System-Wide Quality (`NotebookQualitySnapshot` dataclass):**

| Metric | Type | Source |
|--------|------|--------|
| `timestamp` | float | time.time() |
| `total_entries` | int | all notebook entries |
| `total_agents` | int | distinct authors |
| `total_topics` | int | distinct topics |
| `system_quality_score` | float | mean of per-agent quality_scores |
| `dedup_suppression_rate` | float | from event counters |
| `repetition_alert_rate` | float | from event counters |
| `convergence_count` | int | convergence events since last snapshot |
| `divergence_count` | int | divergence events since last snapshot |
| `stale_entry_rate` | float | fraction of all entries considered stale |
| `per_agent` | list[AgentNotebookQuality] | per-agent breakdown |
| `per_department` | dict[str, float] | department-level quality scores |

### Quality Score Formula

Per-agent `quality_score` (0.0–1.0) is a weighted composite:

```python
quality_score = (
    0.30 * topic_diversity_score     # unique_topics / max(total_entries, 1), capped at 1.0
    + 0.25 * freshness_score         # 1.0 - stale_rate
    + 0.25 * novelty_score           # novel_content_rate
    + 0.10 * convergence_score       # min(convergence_contributions / 3, 1.0)
    + 0.10 * low_repetition_score    # 1.0 if repetition_alerts == 0, else max(0, 1.0 - repetition_alerts * 0.2)
)
```

This formula rewards:
- **Topic diversity** (30%): covering multiple subjects vs. grinding one topic
- **Freshness** (25%): keeping entries current
- **Novelty** (25%): writing new content vs. re-treading old ground
- **Convergence** (10%): contributing to cross-agent knowledge patterns
- **Low repetition** (10%): not triggering repetition detection

The formula is deterministic and computed from frontmatter data only — no LLM calls.

### Engine Pattern (follows EmergenceMetricsEngine)

```
NotebookQualityEngine
  ├── _snapshots: deque[NotebookQualitySnapshot](maxlen=100)
  ├── _event_counters: dict[str, int]  (reset each snapshot)
  ├── latest_snapshot property → last element or None
  ├── snapshots property → list copy
  ├── compute_quality_metrics(records_store, staleness_hours) → NotebookQualitySnapshot
  └── record_event(event_type: str) → None  (increment counters)
```

### When Quality Metrics Are Computed

**Primary trigger: Dream cycle.** Quality metrics computation runs as a dream step — after Step 7g (consolidation) and Step 9 (emergence metrics). This ensures metrics reflect the post-consolidation state.

**Rationale:** Quality metrics require scanning all notebook entries (`list_entries`). This is O(N) I/O over the records repo. Running it every heartbeat (5s) or every notebook write would be wasteful. Dream cycles (every ~4 hours by default) are the natural cadence for ship-level quality assessment. Between dreams, the `latest_snapshot` serves stale-but-reasonable data.

**Event counting is real-time.** The engine subscribes to `NOTEBOOK_SELF_REPETITION`, `CONVERGENCE_DETECTED`, and `DIVERGENCE_DETECTED` events and increments counters immediately. These counters feed into the next snapshot's rates.

---

## Deliverables

### Deliverable 1: NotebookQualityEngine

**File:** `src/probos/knowledge/notebook_quality.py` (NEW)

Create a new module with:

**1a. `AgentNotebookQuality` dataclass:**

```python
@dataclass
class AgentNotebookQuality:
    """Quality metrics for a single agent's notebook corpus."""

    callsign: str = ""
    department: str = ""
    total_entries: int = 0
    unique_topics: int = 0
    entries_per_topic_avg: float = 0.0
    entries_per_topic_max: int = 0
    mean_revision: float = 0.0
    max_revision: int = 0
    novel_content_rate: float = 0.0
    stale_rate: float = 0.0
    convergence_contributions: int = 0
    repetition_alerts: int = 0
    quality_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
```

**1b. `NotebookQualitySnapshot` dataclass:**

```python
@dataclass
class NotebookQualitySnapshot:
    """Ship-level notebook quality metrics at a point in time."""

    timestamp: float = 0.0
    total_entries: int = 0
    total_agents: int = 0
    total_topics: int = 0
    system_quality_score: float = 0.0
    dedup_suppression_rate: float = 0.0
    repetition_alert_rate: float = 0.0
    convergence_count: int = 0
    divergence_count: int = 0
    stale_entry_rate: float = 0.0
    per_agent: list[AgentNotebookQuality] = field(default_factory=list)
    per_department: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["per_agent"] = [a.to_dict() if hasattr(a, 'to_dict') else a for a in self.per_agent]
        return d
```

**1c. `NotebookQualityEngine` class:**

```python
class NotebookQualityEngine:
    """Aggregates notebook quality metrics from RecordsStore data.

    Follows EmergenceMetricsEngine pattern: snapshot deque + properties + compute method.
    """

    def __init__(self, staleness_hours: float = 72.0) -> None:
        self._snapshots: deque[NotebookQualitySnapshot] = deque(maxlen=100)
        self._staleness_hours = staleness_hours
        # Event counters (reset each compute cycle)
        self._dedup_suppressions: int = 0
        self._dedup_writes: int = 0
        self._repetition_alerts: int = 0
        self._convergence_events: int = 0
        self._divergence_events: int = 0
        # Per-agent event tracking
        self._agent_convergences: dict[str, int] = defaultdict(int)
        self._agent_repetitions: dict[str, int] = defaultdict(int)

    @property
    def latest_snapshot(self) -> NotebookQualitySnapshot | None:
        return self._snapshots[-1] if self._snapshots else None

    @property
    def snapshots(self) -> list[NotebookQualitySnapshot]:
        return list(self._snapshots)

    def record_event(self, event_type: str, **kwargs: Any) -> None:
        """Record a notebook pipeline event for quality metrics."""
        if event_type == "dedup_suppression":
            self._dedup_suppressions += 1
        elif event_type == "dedup_write":
            self._dedup_writes += 1
        elif event_type == "repetition_alert":
            self._repetition_alerts += 1
            agent = kwargs.get("callsign", "")
            if agent:
                self._agent_repetitions[agent] += 1
        elif event_type == "convergence":
            self._convergence_events += 1
            for agent in kwargs.get("agents", []):
                self._agent_convergences[agent] += 1
        elif event_type == "divergence":
            self._divergence_events += 1

    async def compute_quality_metrics(
        self,
        records_store: Any,
        staleness_hours: float | None = None,
    ) -> NotebookQualitySnapshot:
        """Compute full quality snapshot from RecordsStore notebook data.

        Called during dream cycle. Scans all notebook entries, computes
        per-agent quality scores, and produces a system-wide snapshot.
        """
        # Implementation details below
```

**1d. `compute_quality_metrics()` implementation:**

```python
async def compute_quality_metrics(self, records_store, staleness_hours=None):
    staleness = staleness_hours or self._staleness_hours
    now = time.time()
    staleness_cutoff = now - (staleness * 3600)

    # Scan all notebook entries
    try:
        entries = await records_store.list_entries("notebooks")
    except Exception:
        logger.debug("AD-555: Failed to list notebook entries", exc_info=True)
        return NotebookQualitySnapshot(timestamp=now)

    # Group by author
    by_author: dict[str, list[dict]] = defaultdict(list)
    all_topics: set[str] = set()
    stale_count = 0

    for entry in entries:
        fm = entry.get("frontmatter", {})
        author = fm.get("author", "unknown")
        topic = fm.get("topic", entry["path"].split("/")[-1].replace(".md", ""))
        by_author[author].append(entry)
        all_topics.add(topic)

        # Staleness check
        updated_str = fm.get("updated", "")
        if updated_str:
            try:
                entry_ts = datetime.fromisoformat(updated_str).timestamp()
                if entry_ts < staleness_cutoff:
                    stale_count += 1
            except (ValueError, OSError):
                pass

    # Per-agent quality
    per_agent: list[AgentNotebookQuality] = []
    for callsign, agent_entries in sorted(by_author.items()):
        aq = _compute_agent_quality(
            callsign, agent_entries, staleness_cutoff,
            convergence_contributions=self._agent_convergences.get(callsign, 0),
            repetition_alerts=self._agent_repetitions.get(callsign, 0),
        )
        per_agent.append(aq)

    # Per-department aggregation
    per_department: dict[str, list[float]] = defaultdict(list)
    for aq in per_agent:
        if aq.department:
            per_department[aq.department].append(aq.quality_score)
    dept_scores = {
        dept: round(sum(scores) / len(scores), 3)
        for dept, scores in per_department.items()
        if scores
    }

    # System-wide
    total_writes = self._dedup_writes + self._dedup_suppressions
    snapshot = NotebookQualitySnapshot(
        timestamp=now,
        total_entries=len(entries),
        total_agents=len(by_author),
        total_topics=len(all_topics),
        system_quality_score=round(
            sum(a.quality_score for a in per_agent) / max(len(per_agent), 1), 3
        ),
        dedup_suppression_rate=round(
            self._dedup_suppressions / max(total_writes, 1), 3
        ),
        repetition_alert_rate=round(
            self._repetition_alerts / max(total_writes, 1), 3
        ),
        convergence_count=self._convergence_events,
        divergence_count=self._divergence_events,
        stale_entry_rate=round(stale_count / max(len(entries), 1), 3),
        per_agent=per_agent,
        per_department=dept_scores,
    )

    self._snapshots.append(snapshot)
    self._reset_counters()
    return snapshot

def _reset_counters(self) -> None:
    """Reset event counters after snapshot. Preserves per-agent cumulative counts."""
    self._dedup_suppressions = 0
    self._dedup_writes = 0
    self._repetition_alerts = 0
    self._convergence_events = 0
    self._divergence_events = 0
```

**1e. `_compute_agent_quality()` module-level function:**

```python
def _compute_agent_quality(
    callsign: str,
    entries: list[dict],
    staleness_cutoff: float,
    *,
    convergence_contributions: int = 0,
    repetition_alerts: int = 0,
) -> AgentNotebookQuality:
    """Compute quality metrics for a single agent's notebook entries."""
    total = len(entries)
    if total == 0:
        return AgentNotebookQuality(callsign=callsign, quality_score=0.0)

    department = ""
    topics: dict[str, int] = defaultdict(int)  # topic -> entry count
    revisions: list[int] = []
    stale = 0
    novel = 0  # entries with revision == 1 (first version)

    for entry in entries:
        fm = entry.get("frontmatter", {})
        if not department:
            department = fm.get("department", "")
        topic = fm.get("topic", entry["path"].split("/")[-1].replace(".md", ""))
        topics[topic] += 1
        rev = fm.get("revision", 1)
        revisions.append(rev)
        if rev == 1:
            novel += 1
        updated_str = fm.get("updated", "")
        if updated_str:
            try:
                ts = datetime.fromisoformat(updated_str).timestamp()
                if ts < staleness_cutoff:
                    stale += 1
            except (ValueError, OSError):
                pass

    unique_topics = len(topics)
    entries_per_topic_max = max(topics.values()) if topics else 0
    stale_rate = stale / total
    novel_content_rate = novel / total

    # Quality score (weighted composite)
    topic_diversity = min(unique_topics / max(total, 1), 1.0)
    freshness = 1.0 - stale_rate
    convergence_score_val = min(convergence_contributions / 3, 1.0)
    low_rep = max(0.0, 1.0 - repetition_alerts * 0.2) if repetition_alerts > 0 else 1.0

    quality = round(
        0.30 * topic_diversity
        + 0.25 * freshness
        + 0.25 * novel_content_rate
        + 0.10 * convergence_score_val
        + 0.10 * low_rep,
        3,
    )

    return AgentNotebookQuality(
        callsign=callsign,
        department=department,
        total_entries=total,
        unique_topics=unique_topics,
        entries_per_topic_avg=round(total / max(unique_topics, 1), 1),
        entries_per_topic_max=entries_per_topic_max,
        mean_revision=round(sum(revisions) / total, 1),
        max_revision=max(revisions) if revisions else 0,
        novel_content_rate=round(novel_content_rate, 3),
        stale_rate=round(stale_rate, 3),
        convergence_contributions=convergence_contributions,
        repetition_alerts=repetition_alerts,
        quality_score=quality,
    )
```

### Deliverable 2: Dream Cycle Integration

**File:** `src/probos/cognitive/dreaming.py`

Add a new dream step after Step 9 (emergence metrics). This is Step 10: Notebook Quality Metrics.

**2a.** In the main dream method, after Step 9 completes:

```python
# ── Step 10: Notebook Quality Metrics (AD-555) ──
if hasattr(self, '_notebook_quality_engine') and self._notebook_quality_engine:
    try:
        _records = getattr(self._runtime, '_records_store', None)
        if _records:
            _staleness = 72.0
            if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'records'):
                _staleness = getattr(self._runtime.config.records, 'notebook_staleness_hours', 72.0)
            quality_snapshot = await self._notebook_quality_engine.compute_quality_metrics(
                _records, staleness_hours=_staleness
            )
            report.notebook_quality_score = quality_snapshot.system_quality_score
            report.notebook_quality_agents = len(quality_snapshot.per_agent)
            logger.info(
                "AD-555 Step 10: Notebook quality computed — score=%.3f, agents=%d, entries=%d",
                quality_snapshot.system_quality_score,
                len(quality_snapshot.per_agent),
                quality_snapshot.total_entries,
            )
    except Exception:
        logger.debug("AD-555 Step 10: Quality metrics failed", exc_info=True)
```

**2b.** Wire the engine onto the DreamingEngine during initialization. In `__init__`, accept an optional `notebook_quality_engine` parameter:

```python
def __init__(self, ..., notebook_quality_engine: Any = None) -> None:
    ...
    self._notebook_quality_engine = notebook_quality_engine
```

**2c.** Where DreamingEngine is constructed (in `src/probos/startup/phase_dreaming.py` or wherever it's wired), pass the engine:

```python
notebook_quality_engine = getattr(runtime, '_notebook_quality_engine', None)
```

### Deliverable 3: DreamReport Extension

**File:** `src/probos/types.py`

Add notebook quality fields to `DreamReport` (after the AD-557 emergence fields):

```python
# AD-555: Notebook quality
notebook_quality_score: float | None = None
notebook_quality_agents: int = 0
```

### Deliverable 4: Event Wiring

**File:** `src/probos/dream_adapter.py` (or wherever event subscriptions are wired)

Subscribe the NotebookQualityEngine to relevant events. The engine's `record_event()` method should be called when these events fire:

**4a.** In the proactive write path (`src/probos/proactive.py`), after the dedup gate decision:

```python
# AD-555: Record dedup outcome for quality metrics
_quality_engine = getattr(self._runtime, '_notebook_quality_engine', None)
if _quality_engine:
    if dedup_result.get("action") == "suppress":
        _quality_engine.record_event("dedup_suppression")
    else:
        _quality_engine.record_event("dedup_write")
```

**4b.** After AD-552 self-repetition detection emits `NotebookSelfRepetitionEvent`:

```python
# AD-555: Record repetition alert for quality metrics
if _quality_engine:
    _quality_engine.record_event("repetition_alert", callsign=callsign)
```

**4c.** After AD-554 convergence/divergence detection:

```python
# AD-555: Record convergence/divergence for quality metrics
if _quality_engine:
    if convergence_result.get("convergence_detected"):
        _quality_engine.record_event(
            "convergence",
            agents=convergence_result.get("convergence_agents", []),
        )
    if convergence_result.get("divergence_detected"):
        _quality_engine.record_event("divergence")
```

**Important:** These are lightweight counter increments (no I/O). They happen inline in the write path with negligible cost.

### Deliverable 5: Runtime Wiring & Startup

**File:** `src/probos/startup/phase_dreaming.py` (or equivalent startup phase)

**5a.** Create the NotebookQualityEngine during startup and attach to runtime:

```python
# AD-555: Notebook Quality Engine
from probos.knowledge.notebook_quality import NotebookQualityEngine

staleness_hours = 72.0
if hasattr(runtime.config, 'records'):
    staleness_hours = getattr(runtime.config.records, 'notebook_staleness_hours', 72.0)
runtime._notebook_quality_engine = NotebookQualityEngine(staleness_hours=staleness_hours)
```

**5b.** Pass to DreamingEngine constructor (see Deliverable 2b).

### Deliverable 6: API Endpoints

**File:** `src/probos/routers/system.py` (or a new `quality.py` router)

Follow the EmergenceMetrics API pattern exactly:

**6a. `GET /api/notebook-quality`** — Returns latest quality snapshot:

```python
@router.get("/notebook-quality")
async def get_notebook_quality(runtime=Depends(get_runtime)):
    engine = getattr(runtime, "_notebook_quality_engine", None)
    if not engine:
        return {"status": "not_available", "message": "Notebook quality engine not initialized"}
    snapshot = engine.latest_snapshot
    if not snapshot:
        return {"status": "no_data", "message": "No quality metrics computed yet — next dream cycle will generate"}
    return {"status": "ok", **snapshot.to_dict()}
```

**6b. `GET /api/notebook-quality/history`** — Returns quality history:

```python
@router.get("/notebook-quality/history")
async def get_notebook_quality_history(limit: int = 20, runtime=Depends(get_runtime)):
    engine = getattr(runtime, "_notebook_quality_engine", None)
    if not engine:
        return {"status": "not_available", "message": "Notebook quality engine not initialized"}
    snaps = engine.snapshots
    limited = snaps[-limit:] if len(snaps) > limit else snaps
    return {
        "status": "ok",
        "count": len(limited),
        "snapshots": [s.to_dict() for s in limited],
    }
```

**6c. `GET /api/notebook-quality/agent/{callsign}`** — Per-agent quality from latest snapshot:

```python
@router.get("/notebook-quality/agent/{callsign}")
async def get_agent_notebook_quality(callsign: str, runtime=Depends(get_runtime)):
    engine = getattr(runtime, "_notebook_quality_engine", None)
    if not engine or not engine.latest_snapshot:
        return {"status": "no_data"}
    for aq in engine.latest_snapshot.per_agent:
        if aq.callsign.lower() == callsign.lower():
            return {"status": "ok", **aq.to_dict()}
    return {"status": "not_found", "message": f"No quality data for {callsign}"}
```

### Deliverable 7: VitalsMonitor Integration

**File:** `src/probos/agents/medical/vitals_monitor.py`

In `collect_metrics()`, after the AD-557 emergence metrics integration, add notebook quality:

```python
# AD-555: Notebook quality metrics
_quality_engine = None
try:
    _quality_engine = getattr(self._runtime, '_notebook_quality_engine', None)
except Exception:
    pass

if _quality_engine and _quality_engine.latest_snapshot:
    _qs = _quality_engine.latest_snapshot
    metrics["notebook_quality"] = round(_qs.system_quality_score, 3)
    metrics["notebook_entries"] = _qs.total_entries
    metrics["notebook_stale_rate"] = round(_qs.stale_entry_rate, 3)
```

This surfaces notebook quality in the vitals window so it appears in VitalsMonitor's periodic broadcast alongside trust, pool health, etc.

### Deliverable 8: Bridge Alert Integration

**File:** `src/probos/bridge_alerts.py`

**8a.** Add a `check_notebook_quality()` method to `BridgeAlertService`:

```python
def check_notebook_quality(self, quality_snapshot: dict) -> list[BridgeAlert]:
    """AD-555: Check notebook quality metrics for alert conditions."""
    alerts: list[BridgeAlert] = []
    score = quality_snapshot.get("system_quality_score", 1.0)
    stale_rate = quality_snapshot.get("stale_entry_rate", 0.0)

    if score < 0.3:
        alerts.append(BridgeAlert(
            severity=AlertSeverity.ALERT,
            source="notebook_quality",
            alert_type="notebook_quality_low",
            title="Notebook quality critically low",
            detail=f"System notebook quality score {score:.2f} — high noise, low signal across crew notebooks",
            dedup_key="notebook_quality_low",
        ))
    elif score < 0.5:
        alerts.append(BridgeAlert(
            severity=AlertSeverity.ADVISORY,
            source="notebook_quality",
            alert_type="notebook_quality_degraded",
            title="Notebook quality degraded",
            detail=f"System notebook quality score {score:.2f} — recommend reviewing agent observation triggers",
            dedup_key="notebook_quality_degraded",
        ))

    if stale_rate > 0.7:
        alerts.append(BridgeAlert(
            severity=AlertSeverity.ADVISORY,
            source="notebook_quality",
            alert_type="notebook_staleness_high",
            title="High notebook staleness",
            detail=f"{stale_rate:.0%} of notebook entries are stale — crew may not be actively observing",
            dedup_key="notebook_staleness_high",
        ))

    # Per-agent quality alerts
    for agent in quality_snapshot.get("per_agent", []):
        if isinstance(agent, dict):
            aq_score = agent.get("quality_score", 1.0)
            aq_callsign = agent.get("callsign", "unknown")
        else:
            aq_score = getattr(agent, "quality_score", 1.0)
            aq_callsign = getattr(agent, "callsign", "unknown")

        if aq_score < 0.25:
            alerts.append(BridgeAlert(
                severity=AlertSeverity.INFO,
                source="notebook_quality",
                alert_type="agent_quality_low",
                title=f"{aq_callsign}: notebook quality low",
                detail=f"{aq_callsign} quality score {aq_score:.2f} — may need different observation triggers",
                dedup_key=f"agent_quality_low_{aq_callsign}",
            ))

    return alerts
```

**8b.** Call `check_notebook_quality()` after each quality metrics computation in the dream cycle step (Deliverable 2a), passing `quality_snapshot.to_dict()`. Emit alerts via the bridge alert delivery mechanism.

### Deliverable 9: Config Knobs

**File:** `src/probos/config.py`

Add to `RecordsConfig` (after the AD-554 settings):

```python
# AD-555: Notebook quality metrics
notebook_quality_enabled: bool = True
notebook_quality_low_threshold: float = 0.3
notebook_quality_warn_threshold: float = 0.5
notebook_staleness_alert_rate: float = 0.7
```

Use these thresholds in Bridge alert checks (Deliverable 8) instead of hardcoded values.

### Deliverable 10: Event Type

**File:** `src/probos/events.py`

Add a new EventType:

```python
NOTEBOOK_QUALITY_UPDATED = "notebook_quality_updated"
```

Emit this event after each quality snapshot is computed (in the dream step), carrying the `system_quality_score` as the event data. No typed dataclass needed — the data is simple enough for a plain dict payload: `{"system_quality_score": float, "total_entries": int, "total_agents": int}`.

---

## Files Modified (Expected)

| File | Change |
|------|--------|
| `src/probos/knowledge/notebook_quality.py` | NEW — `AgentNotebookQuality`, `NotebookQualitySnapshot`, `NotebookQualityEngine`, `_compute_agent_quality()` |
| `src/probos/cognitive/dreaming.py` | Step 10: notebook quality computation |
| `src/probos/types.py` | `DreamReport.notebook_quality_score`, `.notebook_quality_agents` |
| `src/probos/proactive.py` | Event recording (dedup outcome, repetition, convergence) |
| `src/probos/startup/phase_dreaming.py` | Engine creation + wiring |
| `src/probos/routers/system.py` | `/api/notebook-quality`, `/api/notebook-quality/history`, `/api/notebook-quality/agent/{callsign}` |
| `src/probos/agents/medical/vitals_monitor.py` | Notebook quality in `collect_metrics()` |
| `src/probos/bridge_alerts.py` | `check_notebook_quality()` |
| `src/probos/config.py` | `RecordsConfig` quality settings |
| `src/probos/events.py` | `NOTEBOOK_QUALITY_UPDATED` event type |
| `tests/test_ad555_notebook_quality.py` | NEW — test file |

---

## Prior Work to Absorb

| Source | What to Reuse | How |
|--------|---------------|-----|
| EmergenceMetricsEngine (AD-557) | Snapshot deque + properties + `to_dict()` + dream step pattern + API endpoints | Template for NotebookQualityEngine structure |
| `list_entries("notebooks")` (RecordsStore) | Lists all notebook entries with frontmatter | Primary data source for quality aggregation |
| `get_stats()` (RecordsStore) | Total documents, per-directory counts | Supplementary data |
| Frontmatter schema (AD-550/553) | `revision`, `created`, `updated`, `metrics`, `topic`, `author`, `department` | All fields needed for quality scoring |
| `NotebookSelfRepetitionEvent` (AD-552) | Event with `agent_callsign`, `revision`, `novelty`, `suppressed` | Subscribe for repetition counter |
| `ConvergenceDetectedEvent` (AD-554) | Event with `agents`, `departments`, `topic`, `coherence` | Subscribe for convergence counter |
| `DivergenceDetectedEvent` (AD-554) | Event with `agents`, `departments`, `topic`, `similarity` | Subscribe for divergence counter |
| `collect_metrics()` (VitalsMonitor) | Pattern for adding new keys to vitals dict | Follow same pattern for notebook_quality |
| `check_vitals()` (BridgeAlertService) | Pattern for threshold-based alert generation | Follow same pattern for quality alerts |
| BridgeAlert delivery (ward_room_router) | AlertSeverity routing: INFO→department, ADVISORY/ALERT→All Hands | Quality alerts use same delivery |
| Proactive write path (lines 1400-1656) | Dedup gate → repetition check → metric capture → convergence scan | Hook event recording after each stage |
| `notebook_summary` (proactive.py 1049) | Already computes `total_entries`/`total_topics` per-agent | Similar computation, but AD-555 is system-wide + persisted |
| Dream Step 7g (dreaming.py ~530-663) | Consolidation + convergence in dream cycle | Step 10 runs after Step 9 |
| AD-554 `check_cross_agent_convergence()` | Convergence/divergence result dict structure | Event data shape for counter |
| System router emergence endpoints | `/api/emergence`, `/api/emergence/history` response format | Template for `/api/notebook-quality` |

---

## Tests (30 minimum)

### TestAgentNotebookQuality (5 tests)

1. `_compute_agent_quality()` returns 0.0 quality for agent with no entries
2. `_compute_agent_quality()` computes correct topic diversity (3 topics / 5 entries = 0.6)
3. `_compute_agent_quality()` computes correct stale_rate from timestamps
4. `_compute_agent_quality()` novel_content_rate correctly counts revision-1 entries
5. `_compute_agent_quality()` quality_score weighted composite matches formula

### TestNotebookQualityEngine (8 tests)

6. Engine starts with empty snapshot deque
7. `latest_snapshot` returns None before any computation
8. `compute_quality_metrics()` returns valid snapshot with per-agent data
9. `compute_quality_metrics()` groups entries by author correctly
10. `compute_quality_metrics()` computes system_quality_score as mean of agent scores
11. `compute_quality_metrics()` computes stale_entry_rate correctly
12. `compute_quality_metrics()` appends to snapshot deque (multiple calls = multiple snapshots)
13. `compute_quality_metrics()` degrades gracefully when `list_entries()` fails

### TestEventRecording (5 tests)

14. `record_event("dedup_suppression")` increments suppression counter
15. `record_event("dedup_write")` increments write counter
16. `record_event("repetition_alert", callsign="Chapel")` increments per-agent counter
17. `record_event("convergence", agents=["Chapel", "Cortez"])` increments convergence and per-agent
18. Event counters reset after `compute_quality_metrics()` (except per-agent cumulative)

### TestDedup&RepetitionRates (3 tests)

19. `dedup_suppression_rate` correctly computed from suppression/total counts
20. `repetition_alert_rate` correctly computed with zero writes (no division error)
21. Rates reflect events recorded since last snapshot only

### TestQualityScore (4 tests)

22. Perfect agent (diverse topics, all fresh, all novel, convergence, no repetition) scores near 1.0
23. Poor agent (one topic, all stale, all updates, no convergence, many repetitions) scores near 0.0
24. System quality score is mean of per-agent scores
25. Per-department scores correctly aggregate agent scores

### TestBridgeAlerts (3 tests)

26. `check_notebook_quality()` emits ALERT when system score < 0.3
27. `check_notebook_quality()` emits ADVISORY when system score < 0.5
28. `check_notebook_quality()` emits INFO for individual agents with score < 0.25

### TestAPIEndpoints (3 tests)

29. `GET /api/notebook-quality` returns "no_data" when no snapshot exists
30. `GET /api/notebook-quality` returns snapshot dict when available
31. `GET /api/notebook-quality/agent/{callsign}` returns per-agent data

### TestVitalsIntegration (2 tests)

32. VitalsMonitor `collect_metrics()` includes `notebook_quality` when engine available
33. VitalsMonitor `collect_metrics()` omits notebook keys when engine unavailable

---

## Validation Checklist

- [ ] `NotebookQualityEngine` follows EmergenceMetricsEngine pattern (deque, properties, compute method)
- [ ] `compute_quality_metrics()` scans all notebook entries via `list_entries("notebooks")`
- [ ] Per-agent quality computed with weighted composite formula
- [ ] Quality score range validated (0.0–1.0)
- [ ] Event counters increment correctly from proactive write path
- [ ] Counters reset after each snapshot computation
- [ ] Per-agent convergence/repetition counts are cumulative across snapshots
- [ ] Dream Step 10 runs after Step 9 (emergence metrics)
- [ ] DreamReport extended with `notebook_quality_score` and `notebook_quality_agents`
- [ ] API endpoints follow emergence pattern (`/api/notebook-quality`, `/history`, `/agent/{callsign}`)
- [ ] VitalsMonitor surfaces `notebook_quality`, `notebook_entries`, `notebook_stale_rate`
- [ ] Bridge alerts fire at configurable thresholds (system <0.3 = ALERT, <0.5 = ADVISORY)
- [ ] Per-agent alerts at INFO severity for individual quality < 0.25
- [ ] Config knobs added to RecordsConfig (4 new fields)
- [ ] `NOTEBOOK_QUALITY_UPDATED` event type added
- [ ] Graceful degradation — engine failure does not block dream cycle
- [ ] No new async calls to VitalsMonitor — engine reads RecordsStore only
- [ ] All existing AD-550/551/552/553/554 tests still pass (0 regressions)
- [ ] Float values rounded to 3 decimal places
- [ ] `to_dict()` produces JSON-serializable output
- [ ] No new external dependencies

---

## Scope Exclusions (Explicit)

These are NOT part of AD-555:

1. **HXI frontend components** — AD-555 delivers the backend (engine, API, alerts). Frontend visualization is deferred to AD-562 (Knowledge Browser), which depends on AD-555's API endpoints. The API is designed to be consumed by AD-562's React components.

2. **Knowledge linting** — inconsistency detection, coverage gaps, missing cross-references. Deferred to **AD-563** (Knowledge Linting). AD-555 is quality *scoring*, not quality *correction*.

3. **Forced consolidation** — The roadmap mentions `NOTEBOOK_MAX_ENTRIES_PER_TOPIC = 5` as a forced consolidation trigger. Deferred to **AD-564** (Quality-Triggered Forced Consolidation). The quality engine *reports* high entries-per-topic; automated consolidation is a separate concern.

4. **Quality-based routing changes** — AD-555 does not modify Hebbian routing weights or trust scores based on quality. Deferred to **AD-565** (Quality-Informed Routing & Counselor Diagnostics). AD-565 uses quality scores as a Hebbian weight signal and surfaces quality data to the Counselor as a diagnostic wellness dimension.

---

## Notes

- **No staleness_hours duplication.** RecordsConfig already has `notebook_staleness_hours = 72.0` (AD-550). AD-555 reuses this value for stale_rate computation. No new staleness config needed.
- **Per-agent event counts are cumulative.** Unlike the per-snapshot counters (dedup_suppressions, convergence_events) which reset after each snapshot, per-agent convergence_contributions and repetition_alerts accumulate across the engine's lifetime. This gives a running picture of which agents are most active in convergence and which trigger repetition most often.
- **Novel content rate ≠ novelty from AD-552.** AD-552's novelty score is `1.0 - similarity` (how different new content is from existing). AD-555's novel_content_rate is the fraction of entries that are *first writes* (revision == 1) vs. *updates* to existing entries. Different metrics, complementary signals.
- **Quality score is relative, not absolute.** A crew that's been running for 72h will have different score distributions than one running for 2h. The thresholds (0.3/0.5) are tuned for steady-state operation. During cold start, all agents will score near 1.0 (all entries are first writes, none are stale).
- **Dream cycle cadence is sufficient.** Quality metrics computed every ~4 hours. Between dreams, `latest_snapshot` serves the most recent data. Real-time quality tracking (per-write) would add complexity for marginal value — the quality picture changes slowly.
- **HXI scope deferral rationale:** The roadmap spec says "(2) Quality dashboard: Surface notebook quality metrics in HXI alongside existing VitalsMonitor displays." However, the HXI currently has NO notebook/records visualization at all (confirmed by research). Building a quality dashboard requires first building the data display infrastructure, which is AD-562's scope. AD-555 delivers the data layer; AD-562 delivers the visualization. This is cleaner separation of concerns.
