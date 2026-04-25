# Build Prompt: AD-554 — Real-Time Cross-Agent Convergence & Divergence Detection

**Ticket:** AD-554
**Priority:** Medium-High (knowledge extraction pipeline, step 5 of 7 — most commercially significant)
**Scope:** Real-time cross-agent notebook convergence/divergence detection, typed events, Bridge notification, convergence report auto-generation
**Principles Compliance:** DRY (reuse similarity functions, existing BridgeAlert infrastructure), Fail Fast (log-and-degrade), Single Responsibility (scan function in RecordsStore, event emission in proactive, alerts in BridgeAlertService), Law of Demeter (access notebooks via RecordsStore API)
**Dependencies:** AD-550 (Notebook Dedup — COMPLETE), AD-551 (Notebook Consolidation — COMPLETE, provides batch convergence), AD-553 (Quantitative Baseline — COMPLETE), AD-434 (Ship's Records — COMPLETE), AD-410 (Bridge Alerts — COMPLETE)

---

## Context

AD-551 detects convergence *retrospectively* during dream consolidation — a batch process that runs every few hours. But the iatrogenic trust detection case study showed that convergence between Chapel, Cortez, and Keiko was only discovered by *manual review* of 419 files. By the time the dream cycle ran, the finding was hours old.

AD-554 adds **real-time convergence detection**. After every notebook write, an incremental scan checks if the just-written content converges with recent notebooks from agents in *other departments*. When 2+ agents from 2+ departments independently reach similar conclusions, a `CONVERGENCE_DETECTED` event fires immediately and the Bridge is notified.

The Karpathy annotation adds **divergence detection** — the inverse. When agents write about the *same topic* but with meaningfully different conclusions, that's potentially more actionable than agreement. Convergence validates; divergence identifies knowledge frontiers where the crew's understanding is incomplete.

**Why this matters commercially:** Each convergence event is a concrete case study for the collaborative intelligence thesis — "Same LLM, different sovereign contexts → qualitatively different collaborative output." This is the most legible demonstration of ProbOS's value proposition.

---

## Architecture

### Real-Time Convergence Scan

A new method `check_cross_agent_convergence()` on `RecordsStore` runs an incremental scan after each notebook write. Unlike the dream Step 7g full N×N pairwise scan, this is targeted:

1. The *just-written* entry is the anchor
2. Scan recent entries (within `staleness_hours`, default 72h) from OTHER agents in OTHER departments
3. Cap at `max_scan_per_agent` entries (default 5) per other agent — most recent first
4. Compute Jaccard similarity between the anchor and each candidate
5. If `convergence_threshold` (default 0.5) is met by entries from `min_agents` (default 2, including the writer) across `min_departments` (default 2):
   → Convergence detected

**Performance:** O(agents × max_scan_per_agent) ≈ O(55 × 5) = ~275 comparisons max. Jaccard on word sets is microsecond-level. Total: <10ms even worst case. No async I/O beyond file reads (which are local).

### Divergence Detection

Divergence is checked alongside convergence using the same scan data. When two agents have entries on the *same topic slug* but with *low* content similarity (below `divergence_threshold`, default 0.3), AND they are from different departments, that's a divergence signal.

The key insight: convergence = same conclusions from different analytical lenses (high similarity, different departments). Divergence = different conclusions on the same subject matter (same topic, low similarity, different departments). The scan collects both signals in one pass.

### Event Flow

```
Agent writes [NOTEBOOK topic-slug]...[/NOTEBOOK]
  → AD-550 dedup gate (existing)
  → AD-552 frequency check (existing)
  → AD-553 metric capture (existing)
  → write_notebook() succeeds
  → AD-554: check_cross_agent_convergence() [NEW]
       ↓ convergence found?
       → emit ConvergenceDetectedEvent
       → BridgeAlertService.check_realtime_convergence() → BridgeAlert
       → auto-generate convergence report in Ship's Records
       ↓ divergence found?
       → emit DivergenceDetectedEvent
       → BridgeAlertService.check_divergence() → BridgeAlert
```

**Important:** The scan runs AFTER the write succeeds — it must not block or gate the write. Convergence/divergence detection is observational, not preventive.

---

## Deliverables

### Deliverable 1: Cross-Agent Convergence Scan

**File:** `src/probos/knowledge/records_store.py`

New method on `RecordsStore`:

```python
async def check_cross_agent_convergence(
    self,
    anchor_callsign: str,
    anchor_department: str,
    anchor_topic_slug: str,
    anchor_content: str,
    *,
    convergence_threshold: float = 0.5,
    divergence_threshold: float = 0.3,
    staleness_hours: float = 72.0,
    max_scan_per_agent: int = 5,
    min_convergence_agents: int = 2,
    min_convergence_departments: int = 2,
) -> dict[str, Any]:
```

**Algorithm:**

```
1. List all agent directories under notebooks/ (excluding anchor_callsign)
2. For each other agent directory:
   a. List .md files, parse frontmatter for updated timestamp + department
   b. Filter: within staleness window, sort by recency, take top max_scan_per_agent
   c. Read content, compute Jaccard similarity against anchor_content
   d. Track results: {agent_callsign, department, topic_slug, similarity, path}
3. Convergence check:
   a. Select matches with similarity >= convergence_threshold
   b. Include the anchor agent in the set
   c. Count unique agents and unique departments
   d. If agents >= min_convergence_agents AND departments >= min_convergence_departments:
      → convergence detected
4. Divergence check:
   a. Select entries with the SAME topic_slug as anchor_topic_slug
   b. Among those, find entries with similarity < divergence_threshold
   c. If any are from a different department:
      → divergence detected
5. Return result dict
```

**Return value:**

```python
{
    "convergence_detected": bool,
    "convergence_agents": list[str],       # callsigns including anchor
    "convergence_departments": list[str],  # departments including anchor's
    "convergence_coherence": float,        # avg pairwise similarity among converging entries
    "convergence_topic": str,              # inferred topic (same as Step 7g: top-3 common words)
    "convergence_matches": list[dict],     # [{callsign, department, topic_slug, similarity, path}]
    "divergence_detected": bool,
    "divergence_agents": list[str],        # callsigns with divergent views
    "divergence_departments": list[str],
    "divergence_topic": str,               # the shared topic_slug
    "divergence_similarity": float,        # lowest similarity in divergent pair
    "divergence_matches": list[dict],      # [{callsign, department, topic_slug, similarity, path}]
}
```

Use `_jaccard_similarity()` already defined in the same file (line 34). Do NOT import from `cognitive/similarity.py` — RecordsStore uses its own local copy (string-based, not set-based) and changing this would add a dependency.

### Deliverable 2: Typed Event Dataclasses

**File:** `src/probos/events.py`

**2a.** Add `DIVERGENCE_DETECTED` to EventType enum (after `CONVERGENCE_DETECTED`):
```python
DIVERGENCE_DETECTED = "divergence_detected"  # AD-554: cross-agent divergence
```

**2b.** Add typed `ConvergenceDetectedEvent` dataclass (currently missing — only the EventType exists):
```python
@dataclass
class ConvergenceDetectedEvent(BaseEvent):
    event_type: EventType = field(default=EventType.CONVERGENCE_DETECTED, init=False)
    agents: list[str] = field(default_factory=list)       # contributing callsigns
    departments: list[str] = field(default_factory=list)   # contributing departments
    topic: str = ""
    coherence: float = 0.0
    source: str = ""  # "realtime" or "dream_consolidation"
    report_path: str = ""
```

**2c.** Add typed `DivergenceDetectedEvent` dataclass:
```python
@dataclass
class DivergenceDetectedEvent(BaseEvent):
    event_type: EventType = field(default=EventType.DIVERGENCE_DETECTED, init=False)
    agents: list[str] = field(default_factory=list)       # diverging callsigns
    departments: list[str] = field(default_factory=list)
    topic: str = ""
    similarity: float = 0.0  # how different they are (lower = more divergent)
```

### Deliverable 3: Proactive Write Path Integration

**File:** `src/probos/proactive.py`

After the `write_notebook()` call succeeds (after line 1549), add the real-time convergence/divergence check:

```python
# AD-554: Real-time cross-agent convergence/divergence detection
_conv_enabled = True
if hasattr(self._runtime, 'config') and hasattr(self._runtime.config, 'records'):
    _conv_enabled = getattr(
        self._runtime.config.records, 'realtime_convergence_enabled', True
    )

if _conv_enabled and department:
    try:
        conv_result = await self._runtime._records_store.check_cross_agent_convergence(
            anchor_callsign=callsign,
            anchor_department=department,
            anchor_topic_slug=topic_slug,
            anchor_content=notebook_content,
        )

        if conv_result.get("convergence_detected"):
            # 1. Auto-generate convergence report
            report_path = await self._write_convergence_report(
                conv_result, callsign, topic_slug,
            )
            conv_result["report_path"] = report_path

            # 2. Emit typed event
            if hasattr(self._runtime, '_emit_event'):
                from probos.events import ConvergenceDetectedEvent
                evt = ConvergenceDetectedEvent(
                    agents=conv_result["convergence_agents"],
                    departments=conv_result["convergence_departments"],
                    topic=conv_result.get("convergence_topic", topic_slug),
                    coherence=conv_result.get("convergence_coherence", 0.0),
                    source="realtime",
                    report_path=report_path or "",
                )
                try:
                    await self._runtime._emit_event(evt.to_dict())
                except Exception:
                    logger.debug("AD-554: Convergence event emission failed", exc_info=True)

            # 3. Bridge Alert
            await self._emit_convergence_bridge_alert(conv_result)

            logger.info(
                "AD-554: Real-time convergence detected! %d agents from %d departments on %s",
                len(conv_result["convergence_agents"]),
                len(conv_result["convergence_departments"]),
                conv_result.get("convergence_topic", topic_slug),
            )

        if conv_result.get("divergence_detected"):
            # 1. Emit typed event
            if hasattr(self._runtime, '_emit_event'):
                from probos.events import DivergenceDetectedEvent
                evt = DivergenceDetectedEvent(
                    agents=conv_result["divergence_agents"],
                    departments=conv_result["divergence_departments"],
                    topic=conv_result.get("divergence_topic", topic_slug),
                    similarity=conv_result.get("divergence_similarity", 0.0),
                )
                try:
                    await self._runtime._emit_event(evt.to_dict())
                except Exception:
                    logger.debug("AD-554: Divergence event emission failed", exc_info=True)

            # 2. Bridge Alert
            await self._emit_divergence_bridge_alert(conv_result)

            logger.info(
                "AD-554: Divergence detected! %s disagree on %s (similarity=%.2f)",
                ", ".join(conv_result["divergence_agents"]),
                conv_result.get("divergence_topic", topic_slug),
                conv_result.get("divergence_similarity", 0.0),
            )

    except Exception:
        logger.debug("AD-554: Cross-agent scan failed for %s/%s", callsign, topic_slug, exc_info=True)
```

**Helper methods on ProactiveExecutor:**

**3a. `_write_convergence_report()`**: Auto-generate a convergence report in Ship's Records. Follow the dream Step 7g format (lines 624-643 of dreaming.py) — same structure, same path pattern (`reports/convergence/convergence-{timestamp}.md`), but add `source: realtime` to distinguish from dream-detected convergence. Write via `self._runtime._records_store.write_entry()`.

The report content should include:
```markdown
## Real-Time Convergence Report

**Detected:** {timestamp}
**Source:** Real-time notebook monitor

**Agents:** {agent1, agent2, ...}
**Departments:** {dept1, dept2, ...}
**Coherence:** {coherence:.3f}

## Contributing Perspectives

### {agent1} ({department1})
{first 300 chars of their entry}

### {agent2} ({department2})
{first 300 chars of their entry}
```

To build the perspectives section, read each converging agent's entry content from the `convergence_matches` list in the result. Each match dict has a `path` field.

**3b. `_emit_convergence_bridge_alert()`**: Create and deliver a BridgeAlert. Use the existing `_deliver_bridge_alert_fn` pattern from dream_adapter.py. Access `BridgeAlertService` via `self._runtime._bridge_alerts` (same as dream_adapter uses).

```python
async def _emit_convergence_bridge_alert(self, conv_result: dict) -> None:
    ba_svc = getattr(self._runtime, '_bridge_alerts', None)
    deliver_fn = getattr(self._runtime, '_deliver_bridge_alert', None)
    if not ba_svc or not deliver_fn:
        return

    topic = conv_result.get("convergence_topic", "unknown")
    agents = conv_result.get("convergence_agents", [])
    depts = conv_result.get("convergence_departments", [])
    key = f"realtime_convergence:{topic}"

    if ba_svc._should_emit(key):
        alert = BridgeAlert(
            id=str(uuid4()),
            severity=AlertSeverity.ADVISORY,
            source="notebook_monitor",
            alert_type="realtime_convergence_detected",
            title="Real-Time Crew Convergence",
            detail=(
                f"{len(agents)} agents from {len(depts)} departments "
                f"independently reached convergent conclusions on {topic}"
            ),
            department=None,
            dedup_key=key,
        )
        ba_svc._record(alert)
        try:
            await deliver_fn(alert)
        except Exception:
            logger.debug("AD-554: Bridge alert delivery failed", exc_info=True)
```

**3c. `_emit_divergence_bridge_alert()`**: Same pattern for divergence alerts:

```python
async def _emit_divergence_bridge_alert(self, conv_result: dict) -> None:
    # Same structure as convergence, but:
    #   alert_type = "divergence_detected"
    #   title = "Cross-Department Divergence"
    #   severity = AlertSeverity.ADVISORY
    #   dedup_key = f"divergence:{topic}"
    #   detail = "{agent1} and {agent2} reached different conclusions on {topic}"
```

### Deliverable 4: Bridge Alert Infrastructure

**File:** `src/probos/bridge_alerts.py`

**4a.** Add `check_realtime_convergence()` method on `BridgeAlertService`. This is a convenience method that accepts the `conv_result` dict and returns a list of `BridgeAlert` objects — same pattern as the existing `check_convergence()` but with `source="notebook_monitor"` and `alert_type="realtime_convergence_detected"`.

**4b.** Add `check_divergence()` method on `BridgeAlertService`:

```python
def check_divergence(self, divergence_data: dict) -> list[BridgeAlert]:
    """AD-554: Evaluate cross-agent divergence and emit bridge alerts."""
    alerts: list[BridgeAlert] = []
    if not divergence_data.get("divergence_detected"):
        return alerts

    topic = divergence_data.get("divergence_topic", "unknown")
    agents = divergence_data.get("divergence_agents", [])
    departments = divergence_data.get("divergence_departments", [])
    similarity = divergence_data.get("divergence_similarity", 0.0)
    key = f"divergence:{topic}"

    if self._should_emit(key):
        a = BridgeAlert(
            id=str(uuid.uuid4()),
            severity=AlertSeverity.ADVISORY,
            source="notebook_monitor",
            alert_type="divergence_detected",
            title="Cross-Department Divergence",
            detail=(
                f"{', '.join(agents)} from {', '.join(departments)} "
                f"reached different conclusions on {topic} "
                f"(similarity={similarity:.2f})"
            ),
            department=None,
            dedup_key=key,
        )
        self._record(a)
        alerts.append(a)
    return alerts
```

### Deliverable 5: Config Knobs

**File:** `src/probos/config.py`

Add to `RecordsConfig` (after AD-553 settings):

```python
# AD-554: Real-time convergence/divergence detection
realtime_convergence_enabled: bool = True
realtime_convergence_threshold: float = 0.5   # Jaccard similarity for convergence
realtime_divergence_threshold: float = 0.3    # Below = divergence (same topic, different conclusions)
realtime_convergence_staleness_hours: float = 72.0
realtime_max_scan_per_agent: int = 5
realtime_min_convergence_agents: int = 2      # Including the writer
realtime_min_convergence_departments: int = 2  # Including the writer's department
```

These are separate from the `DreamingConfig` convergence settings (which control batch Step 7g). Real-time and batch detection can have different thresholds.

Update the proactive write path and `check_cross_agent_convergence()` call to read these from `self._runtime.config.records`.

---

## Files Modified (Expected)

| File | Change |
|------|--------|
| `src/probos/knowledge/records_store.py` | `check_cross_agent_convergence()` method |
| `src/probos/events.py` | `DIVERGENCE_DETECTED` EventType, `ConvergenceDetectedEvent`, `DivergenceDetectedEvent` dataclasses |
| `src/probos/proactive.py` | Post-write convergence/divergence scan, `_write_convergence_report()`, `_emit_convergence_bridge_alert()`, `_emit_divergence_bridge_alert()` |
| `src/probos/bridge_alerts.py` | `check_realtime_convergence()`, `check_divergence()` methods |
| `src/probos/config.py` | `RecordsConfig` real-time convergence settings |
| `tests/test_ad554_realtime_convergence.py` | New test file |

---

## Prior Work to Absorb

| Source | What to Reuse | How |
|--------|---------------|-----|
| Dream Step 7g (dreaming.py 530-663) | Pairwise Jaccard + BFS clustering algorithm, convergence report format, topic inference (top-3 common words) | Adapt to incremental scan (one anchor entry vs. N candidates instead of full N×N). Use same report format. Same topic inference logic. |
| `check_notebook_similarity()` Layer 3 (records_store.py 359-401) | Cross-topic scan pattern: list dirs, filter by staleness, sort by recency, cap scan | Extend pattern to cross-AGENT directories instead of cross-topic within one agent |
| `_jaccard_similarity()` (records_store.py 34-42) | Local string-based Jaccard function | Use directly — already in the same file |
| `check_peer_similarity()` (ward_room/threads.py 22-80) | Real-time peer detection pattern: compare incoming content against others, emit event on match | Structural template for real-time cross-agent detection |
| `check_convergence()` (bridge_alerts.py 349-377) | Batch convergence → BridgeAlert pattern | Template for `check_realtime_convergence()` and `check_divergence()` |
| `on_post_dream()` (dream_adapter.py 201-214) | Bridge alert delivery pattern: `loop.create_task(deliver_fn(alert))` | Template for async alert delivery in proactive write path |
| `NotebookSelfRepetitionEvent` (events.py) | Typed event dataclass pattern with `to_dict()` support | Template for `ConvergenceDetectedEvent` and `DivergenceDetectedEvent` |
| Convergence report format (dreaming.py 626-633) | Markdown report structure with agents, departments, coherence, perspectives, shared summary | Same structure for real-time reports, add `source: realtime` field |
| `BridgeAlertService._should_emit()` | Dedup/cooldown mechanism for bridge alerts | Use directly — prevents alert spam for repeated convergence on same topic |

---

## Tests (25 minimum)

### TestCrossAgentConvergenceScan (9 tests)

1. No convergence when only one agent's notebooks exist
2. No convergence when two agents match but are in the same department
3. Convergence detected: 2 agents from 2 departments with similarity >= 0.5
4. Convergence detected: 3 agents from 2 departments (exceeds minimum)
5. No convergence when similarity is below threshold
6. Entries outside staleness window are excluded from scan
7. Max scan per agent cap respected (only most recent N checked)
8. Coherence score computed correctly (average pairwise similarity)
9. Topic inferred from common words across converging entries

### TestDivergenceDetection (5 tests)

10. Divergence detected: same topic_slug, different departments, low similarity
11. No divergence when agents agree (high similarity on same topic)
12. No divergence when low-similarity entries are on different topics
13. No divergence when disagreeing agents are in the same department
14. Divergence similarity value is correct (lowest pairwise similarity)

### TestEventEmission (4 tests)

15. `ConvergenceDetectedEvent` emitted with correct fields (agents, departments, topic, coherence, source="realtime")
16. `DivergenceDetectedEvent` emitted with correct fields (agents, departments, topic, similarity)
17. Event NOT emitted when convergence/divergence not detected
18. `DIVERGENCE_DETECTED` EventType exists in enum

### TestBridgeAlerts (4 tests)

19. `check_realtime_convergence()` returns ADVISORY alert with source="notebook_monitor"
20. `check_divergence()` returns ADVISORY alert with divergence details
21. Bridge alert dedup prevents repeated alerts for same convergence topic
22. No bridge alert when detection is negative

### TestConvergenceReport (2 tests)

23. Convergence report written to Ship's Records at `reports/convergence/convergence-{timestamp}.md`
24. Report contains agents, departments, coherence, and contributing perspectives

### TestConfigKnobs (2 tests)

25. RecordsConfig includes all AD-554 settings with correct defaults
26. Custom config values propagate to scan function parameters

### TestWritePathIntegration (2 tests)

27. Convergence scan runs after successful notebook write (not before, not on suppressed writes)
28. Scan failure does not affect notebook write success (log-and-degrade)

---

## Validation Checklist

- [ ] `check_cross_agent_convergence()` scans only OTHER agents' notebooks (not the writer's)
- [ ] Scan respects staleness window (72h default) and per-agent cap (5 default)
- [ ] Convergence requires entries from min_agents across min_departments
- [ ] Divergence requires same topic_slug + different department + low similarity
- [ ] Both convergence and divergence checked in a single scan pass
- [ ] Scan runs AFTER write_notebook() succeeds (not blocking the write)
- [ ] Scan failure does NOT affect notebook write (log-and-degrade)
- [ ] `ConvergenceDetectedEvent` has `source="realtime"` to distinguish from dream batch
- [ ] `DivergenceDetectedEvent` properly typed with all fields
- [ ] Bridge alerts use `source="notebook_monitor"` and dedup properly
- [ ] Convergence report written to Ship's Records with correct format
- [ ] Config knobs separate from DreamingConfig batch convergence settings
- [ ] All existing AD-550/551/552/553 tests still pass (0 regressions)
- [ ] No new async I/O beyond file reads (local filesystem only)
- [ ] Uses existing `_jaccard_similarity()` in records_store.py (no new dependency)

---

## Notes

- **Real-time = post-write, not blocking.** The cross-agent scan runs after the write succeeds. If the scan fails, the notebook is already safely written. This is detection, not gating.
- **Divergence is low-cost addition.** The same scan that finds convergence also surfaces divergence — it's just the inverse similarity filter on same-topic entries. Including it here avoids a future separate AD.
- **Separate from dream batch detection.** AD-551's Step 7g runs full N×N pairwise clustering across ALL notebooks. AD-554 runs a targeted scan anchored on the just-written entry. They complement each other: real-time catches convergence as it forms, batch catches it retrospectively with broader scope.
- **Department is required for convergence.** The scan guard checks `if _conv_enabled and department:` — if the writing agent has no department (e.g., infrastructure agents), skip the convergence scan entirely. Convergence is a cross-department signal.
- **Config is on RecordsConfig, not DreamingConfig.** The real-time scan is part of the notebook write pipeline, not the dream machinery. Separate config namespaces allow different thresholds for real-time vs. batch.
- **The `_deliver_bridge_alert` function** must be accessible from the proactive executor. Check `self._runtime` for either `_deliver_bridge_alert` (direct function) or `_bridge_alerts` (BridgeAlertService instance). The dream_adapter accesses both via constructor injection; the proactive executor accesses them via `self._runtime`. Verify during implementation that `runtime._bridge_alerts` and `runtime._deliver_bridge_alert` are set — if not, degrade gracefully (emit event but skip bridge alert).
- **Report path collision avoidance.** Use `convergence-{timestamp}-{uuid[:8]}.md` for the report filename to avoid collisions if two convergences are detected in the same second (unlikely but possible).
