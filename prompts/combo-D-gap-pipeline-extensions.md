# Combo D — Gap Pipeline Extensions (AD-539c + AD-539d)

**Status:** Drafted (Wave 20)
**Risk:** low (read-only / observational; extends shipped AD-539 pipeline)
**Depends on:** AD-539 (Knowledge Gap → Qualification Pipeline, COMPLETE — gap_predictor.py:186 GapReport, detect_gaps, classify_gap; dreaming.py Step 8)
**Closes:** GitHub issues #106 (AD-539c), #107 (AD-539d)

---

## Why Combo

Per Wave 5-7 retrospective convention #14 (aggressive pre-deferral) and Wave 8 Combo A precedent: 2 child ADs both deferred from AD-539, both small additive surfaces extending the shipped gap pipeline. Per-prompt overhead × 2 would multiply Builder commit cost ~2×; combo is cleaner.

Both children ship as observational v1 layers — they record/aggregate gap data, never auto-act. That keeps the safety profile bounded; active remediation (AD-539c-i) and federation aggregation (AD-539d-i) are deferred grandchildren.

---

## Combo Discipline

- Each child AD is a separate H2 section (`## AD-NNN: Title`).
- Each child has its own Verify-First grep evidence + implementation + test plan.
- Single Section 0 (EventTypes) at top covers both children's new events.
- Single Tracker section at bottom updates PROGRESS.md / DECISIONS.md / roadmap.md for both.
- Single commit closes both ADs with message `Combo D: AD-539c + AD-539d gap pipeline extensions (observational v1)`.

---

## Section 0 — Combined EventTypes

| EventType | Child | Purpose |
|---|---|---|
| `GAP_REMEDIATION_RECORDED` | AD-539c | Observational record that a remediation candidate exists for a gap (no action taken in v1) |
| `FLEET_GAP_SNAPSHOT_TAKEN` | AD-539d | Per-snapshot trigger of fleet (= local ship) gap aggregation |

Verify no collision with events.py post-Wave-19. v1 has 2 new events; both are fired by observational helpers.

---

## Inter-Child File Conflict Sequencing

- AD-539c touches `src/probos/cognitive/gap_remediation.py` (NEW).
- AD-539d touches `src/probos/cognitive/gap_aggregation.py` (NEW).
- No file conflicts.
- Both register on `runtime` as public attributes (`runtime.gap_remediation_tracker`, `runtime.gap_aggregator`).

---

## AD-539c: Automatic Gap Remediation (Observational v1)

**File:** `src/probos/cognitive/gap_remediation.py` (NEW; ~120 lines)

Observational tracker that records what AD-539's pipeline would auto-remediate IF active remediation were turned on. v1 only RECORDS candidates; never acts. Forcing function for AD-539c-i (active remediation): user/Captain decides to switch from observational to action mode.

```python
@dataclass(frozen=True)
class RemediationCandidate:
    """v1 observational record. AD-539c."""
    gap_id: str  # references GapReport.id
    agent_id: str
    gap_type: str  # "knowledge" | "capability" | "data"
    proposed_action: str  # "trigger_qualification" | "request_data_routing" | "escalate_capability"
    reason: str
    candidate_at: float  # UTC timestamp


class GapRemediationTracker:
    """v1 observational only. Records remediation candidates for gaps. AD-539c."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._candidates: list[RemediationCandidate] = []
        self._max_history = 100  # bounded ring
        self.emit_event: Callable[..., None] | None = None  # sibling pattern AD-456/AD-530

    def record_candidate(self, gap_report: Any) -> RemediationCandidate:
        """Record a remediation candidate for a gap.

        Args:
            gap_report: A GapReport (gap_predictor.py:186). Reads gap_type +
                qualification_path_id + priority to derive proposed_action.

        Returns:
            RemediationCandidate (frozen dataclass). Caller stores or ignores.

        Side effects:
            - Appends to bounded ring (evicts oldest beyond _max_history).
            - Emits GAP_REMEDIATION_RECORDED via emit_event (if set).

        v1 NEVER actually triggers the remediation. It only records what
        the system WOULD do. Active remediation is AD-539c-i.
        """

    def proposed_action_for(self, gap_report: Any) -> str:
        """Map gap → proposed action string (deterministic; no side effects).

        - gap_type="knowledge" + qualification_path_id non-empty → "trigger_qualification"
        - gap_type="data" → "request_data_routing"
        - gap_type="capability" → "escalate_capability"
        - else → "no_action"

        Note (observational hole, AD-539c-i): a `knowledge` gap with an EMPTY
        `qualification_path_id` falls through to `"no_action"` — same return
        as an unrecognized gap_type. v1 accepts this; AD-539c-i may add a
        distinct `"knowledge_no_path"` sentinel if downstream observability
        needs to disambiguate the two fall-through cases.
        """

    def recent_candidates(self, limit: int = 20) -> tuple[RemediationCandidate, ...]:
        """Return most-recent candidates (newest first), capped at limit."""

    def candidates_for_agent(self, agent_id: str) -> tuple[RemediationCandidate, ...]:
        """Return candidates filtered by agent_id (newest first)."""
```

**Wiring (finalize.py):**
```python
def _wire_gap_remediation_tracker(*, runtime, config) -> bool:
    cfg = getattr(config, "gap_pipeline_extensions", None)
    if not cfg or not cfg.remediation_tracker_enabled:
        return False
    runtime.gap_remediation_tracker = GapRemediationTracker(runtime)
    runtime.gap_remediation_tracker.emit_event = runtime.emit_event
    logger.info("AD-539c: GapRemediationTracker initialized (observational v1)")
    return True
```

**Test plan (~10 tests):**
| # | Test | Purpose |
|---|---|---|
| 1 | `test_remediation_candidate_is_frozen_dataclass` | Section 1 contract |
| 2 | `test_record_candidate_returns_candidate` | Happy path |
| 3 | `test_record_candidate_emits_event` | EventType emission |
| 4 | `test_record_candidate_appends_to_history` | Ring buffer behavior |
| 5 | `test_record_candidate_evicts_oldest_at_max_history` | Bounded ring |
| 6 | `test_proposed_action_knowledge_with_qualification_path` | Mapping rule 1 |
| 7 | `test_proposed_action_data_gap` | Mapping rule 2 |
| 8 | `test_proposed_action_capability_gap` | Mapping rule 3 |
| 9 | `test_proposed_action_no_action_for_unknown_type` | Default rule |
| 10 | `test_recent_candidates_returns_descending_order` | Ordering |
| 11 | `test_candidates_for_agent_filters_by_agent_id` | Filter behavior |

---

## AD-539d: Fleet-Level Gap Aggregation (Local-Ship v1)

**File:** `src/probos/cognitive/gap_aggregation.py` (NEW; ~100 lines)

v1 ships **local-ship aggregation** (no federation; "fleet" = current ship's gaps). Federated cross-ship aggregation deferred to AD-539d-i (depends on AD-479 federation).

```python
@dataclass(frozen=True)
class FleetGapSnapshot:
    """v1 local-ship snapshot. AD-539d."""
    snapshot_at: float  # UTC timestamp
    total_gaps: int
    by_gap_type: dict[str, int]  # {"knowledge": N, "capability": N, "data": N}
    by_priority: dict[str, int]  # {"low": N, ..., "critical": N}
    by_department: dict[str, int]  # department → gap count (best-effort via agent ontology lookup)
    top_intents: tuple[tuple[str, int], ...]  # top 5 most-affected intents (intent → gap count)


class FleetGapAggregator:
    """v1 local-ship aggregator. AD-539d.

    Fleet = current ship in v1. Cross-ship federation deferred to AD-539d-i.
    """

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self.emit_event: Callable[..., None] | None = None

    def take_snapshot(self, gap_reports: Iterable[Any]) -> FleetGapSnapshot:
        """Aggregate gap reports into a fleet snapshot.

        Args:
            gap_reports: Iterable of GapReport instances (typically from a recent
                dream cycle's detect_gaps output, OR a persisted set).

        Returns:
            FleetGapSnapshot (frozen dataclass).

        Side effects:
            - Emits FLEET_GAP_SNAPSHOT_TAKEN with snapshot summary.
        """

    def _count_by_field(
        self,
        reports: Iterable[Any],
        field_name: str,
    ) -> dict[str, int]:
        """Generic counter helper. Empty dict for empty input."""

    def _top_intents(
        self,
        reports: Iterable[Any],
        n: int = 5,
    ) -> tuple[tuple[str, int], ...]:
        """Aggregate intent counts across all reports' affected_intent_types."""

    def _resolve_department(self, agent_type: str) -> str:
        """Best-effort department lookup via runtime.ontology.

        Calls `runtime.ontology.get_agent_department(agent_type)` — the live
        ontology API takes `agent_type`, NOT `agent_id` (verified at
        proactive.py:2380, dreaming.py:1098, cognitive_agent.py:985).
        `GapReport.agent_type` (gap_predictor.py:194) is the natural caller
        — `take_snapshot` reads `report.agent_type` directly when bucketing
        by department.

        Unwraps the returned department: returns `dept.department_id` when
        the attribute is present, else `str(dept)` (idiom from
        dreaming.py:1099). Returns empty string when ontology absent,
        `agent_type` not in roster, or any lookup exception.
        """
```

**Wiring (finalize.py):**
```python
def _wire_gap_aggregator(*, runtime, config) -> bool:
    cfg = getattr(config, "gap_pipeline_extensions", None)
    if not cfg or not cfg.fleet_aggregator_enabled:
        return False
    runtime.gap_aggregator = FleetGapAggregator(runtime)
    runtime.gap_aggregator.emit_event = runtime.emit_event
    logger.info("AD-539d: FleetGapAggregator initialized (local-ship v1; federation deferred to AD-539d-i)")
    return True
```

**Test plan (~10 tests):**
| # | Test | Purpose |
|---|---|---|
| 1 | `test_fleet_gap_snapshot_is_frozen_dataclass` | Section contract |
| 2 | `test_take_snapshot_empty_reports_returns_zero_counts` | Edge case |
| 3 | `test_take_snapshot_aggregates_total_count` | Happy path |
| 4 | `test_take_snapshot_groups_by_gap_type` | Counting by gap_type |
| 5 | `test_take_snapshot_groups_by_priority` | Counting by priority |
| 6 | `test_take_snapshot_groups_by_department_via_ontology` | Department resolution |
| 7 | `test_take_snapshot_department_empty_when_ontology_absent` | Defensive |
| 8 | `test_take_snapshot_top_intents_returns_max_5_descending` | top_intents shape |
| 9 | `test_take_snapshot_emits_event_with_summary_payload` | EventType emission |
| 10 | `test_take_snapshot_payload_excludes_agent_ids` | Privacy: aggregate-only payload |

---

## Pydantic config

```python
class GapPipelineExtensionsConfig(BaseModel):
    """AD-539c + AD-539d v1 config."""
    remediation_tracker_enabled: bool = True
    fleet_aggregator_enabled: bool = True
    remediation_max_history: int = 100
```

Wire into `SystemConfig.gap_pipeline_extensions: GapPipelineExtensionsConfig = Field(default_factory=GapPipelineExtensionsConfig)`.

---

## What This Combo Does NOT Change

- **AD-539c-i** (active remediation — actually trigger remediation actions). Forcing function: Captain decides to switch from observational to action mode.
- **AD-539d-i** (federation aggregation — cross-ship gap rollup). Forcing function: AD-479 Federation Hardening ships.
- AD-539 pipeline (`detect_gaps`, `classify_gap`, `map_gap_to_skill`, `trigger_qualification_if_needed`) — all read-only consumers; no modifications.
- `GapReport` dataclass at gap_predictor.py:186 — read-only consumer.
- Dreaming cycle Step 8 — untouched. v1 trackers/aggregators are separate surfaces, not Step 8 modifications.
- WardRoomService, episodic memory, work_item_store — not consumed by either child.

---

## Combo Test Plan

Total: **~21 tests** (11 AD-539c + 10 AD-539d). Per-child files: `tests/test_ad539c_remediation.py`, `tests/test_ad539d_aggregation.py`.

Run focused gates per child during build (Wave 8 Combo A pattern + Wave 13 Combo C pattern).

---

## Combo Tracker Updates

**PROGRESS.md:** prepend single Combo D entry summarizing both children + total test count.

**DECISIONS.md:** single entry under Era V titled `### Combo D: AD-539c + AD-539d gap pipeline extensions (observational v1) (2026-05-03)`. Brief problem/decision per child + 2 deferred grandchildren (AD-539c-i active remediation, AD-539d-i federation aggregation).

**docs/development/roadmap.md:** flip 2 status flags (AD-539c → partial-observational, AD-539d → partial-local-ship). Update AD-539 deferred list to reflect c/d shipped, c-i/d-i deferred.

**GH issues to close (in dispatch):**
- #106 (AD-539c) — close, observational v1 ships
- #107 (AD-539d) — close, local-ship v1 ships

**2 issues closed in single Builder commit.**

---

## Verified Against Codebase (2026-05-03)

```
grep -n "class GapReport\|def detect_gaps\|def classify_gap" src/probos/cognitive/gap_predictor.py
  186: class GapReport (id, agent_id, agent_type, gap_type, description, ...)
  229: def classify_gap
  258: def detect_gaps

grep -n "GAP_REPORT_MAX_PER_DREAM\|gap_reports = detect_gaps" src/probos/cognitive/dreaming.py
  config.py:107: GAP_REPORT_MAX_PER_DREAM
  dreaming.py:1098: gap_reports = detect_gaps(...)

grep -n "_wire_creative_expression\|_wire_classification_gate" src/probos/startup/finalize.py
  (Builder verifies the canonical _wire_<feature> sync def + invocation pattern)

grep -rn "runtime.ontology" src/probos/ | head -3
  acm.py:300/301: runtime.ontology consumer (AD-539d _resolve_department uses this)

# Revision pass (2026-05-03): live ontology API verified
grep -n "get_agent_department" src/probos/proactive.py src/probos/cognitive/dreaming.py
  proactive.py:2380:    dept = self._runtime.ontology.get_agent_department(agent.agent_type)
  dreaming.py:1098:    dept = self._runtime.ontology.get_agent_department(agent.agent_type)
  dreaming.py:1099:    department = dept.department_id if hasattr(dept, 'department_id') else str(dept)
  → confirms signature is get_agent_department(agent_type) and dept-object
    unwrap idiom uses .department_id when present.
```

---

## Acceptance Criteria

- `src/probos/cognitive/gap_remediation.py` exists with `GapRemediationTracker` + `RemediationCandidate`.
- `src/probos/cognitive/gap_aggregation.py` exists with `FleetGapAggregator` + `FleetGapSnapshot`.
- 2 new EventTypes (`GAP_REMEDIATION_RECORDED`, `FLEET_GAP_SNAPSHOT_TAKEN`).
- 2 new public attributes on runtime (`gap_remediation_tracker`, `gap_aggregator`).
- `GapPipelineExtensionsConfig` Pydantic class wired into SystemConfig.
- ~21 tests pass.
- Single commit `Combo D: AD-539c + AD-539d gap pipeline extensions (observational v1)`.
- DECISIONS.md combined entry under Era V.
- roadmap.md 2 status flags flipped.
- GH #106 + #107 BOTH closed.

---

## Hard-Stops (per child)

- **AD-539c:** None expected; pure new file + new public attribute.
- **AD-539d:** `runtime.ontology` not exposed at expected attribute name (would degrade `_resolve_department` to empty-string fallback; not blocking — defensive helper covers it). If any other ontology surface drift, surface.
- **Inter-child:** Both wire into `SystemConfig.gap_pipeline_extensions` — Pydantic field collision is the only realistic risk.
- **Active enforcement scope creep** — if you find yourself adding code that actually triggers remediation actions in AD-539c (vs just recording candidates), STOP. That's AD-539c-i.
- **Federation scope creep** — if AD-539d implementation reaches across federation, STOP. That's AD-539d-i.

---

## Revision (2026-05-03)

Pass-1 review at `prompts/Reviews/combo-D-gap-pipeline-extensions-review.md` shipped ✅ Approved with 0 Required + 1 Recommended + 2 Nits. Polish applied this pass:

1. **Rec1 (AD-539d) — `_resolve_department` signature corrected.** Was `_resolve_department(self, agent_id: str)`; now `_resolve_department(self, agent_type: str)`. Live ontology API at proactive.py:2380, dreaming.py:1098, cognitive_agent.py:985 takes `agent_type`. `GapReport.agent_type` (gap_predictor.py:194) is the natural caller — `take_snapshot` reads `report.agent_type` directly when bucketing by department, avoiding a Demeter-violating `runtime.registry` detour to map `agent_id → agent_type`.
2. **Nit1 (AD-539c) — knowledge-without-path fall-through documented.** `proposed_action_for` docstring now explicitly notes that `gap_type="knowledge"` with empty `qualification_path_id` returns `"no_action"` — same return as unrecognized gap_type. Forcing function for AD-539c-i: add `"knowledge_no_path"` sentinel if downstream observability needs to disambiguate.
3. **Nit2 (AD-539d) — dept-object unwrap idiom documented.** `_resolve_department` docstring now specifies the `dept.department_id if hasattr(dept, 'department_id') else str(dept)` unwrap pattern (idiom from dreaming.py:1099). Prevents Builder from storing the dept object directly and producing `<DepartmentName: ...>` strings in the snapshot's `by_department` dict.

No test-plan churn — test #6 (`test_take_snapshot_groups_by_department_via_ontology`) and test #7 (`test_take_snapshot_department_empty_when_ontology_absent`) still assert the same behavior. No changes to acceptance criteria, hard-stops, EventTypes, file targets, or commit message.

**Verified Against Codebase footer extended** with proactive.py:2380 + dreaming.py:1098-1099 grep evidence.
