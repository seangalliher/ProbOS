# Review: Combo D — AD-539c + AD-539d Gap Pipeline Extensions
**Verdict:** ✅ Approved (build-ready)
**Combo D is observationally clean: both children record/aggregate only, no remediation, no federation.**

Reviewed 2026-05-03 (Wave 20, Pass 1). Tolerance per convention #15: 1 ⚠️ permitted on highest-risk child; this prompt has 0 Required + 1 Recommended + 2 Nits, well within budget.

---

## Required (must fix before building)

_None._

---

## Recommended

### AD-539d — `_resolve_department` signature mismatch with live ontology pattern

**Where:** `prompts/combo-D-gap-pipeline-extensions.md` AD-539d helper signature `_resolve_department(self, agent_id: str) -> str:`.

**Live pattern (verified):**
```
src/probos/proactive.py:2380
    dept = self._runtime.ontology.get_agent_department(agent.agent_type)
src/probos/cognitive/dreaming.py:1098-1099
    dept = self._runtime.ontology.get_agent_department(agent.agent_type)
    department = dept.department_id if hasattr(dept, 'department_id') else str(dept)
```

`runtime.ontology.get_agent_department()` takes `agent_type`, not `agent_id`. `GapReport.agent_type` is already present at `gap_predictor.py:194`, so the natural call site has agent_type in hand. As drafted, the Builder will either (a) reach through `runtime.registry` to map `agent_id → agent_type` (Demeter violation + extra hop) or (b) silently change the signature.

**Fix:** Change helper signature to `_resolve_department(self, agent_type: str) -> str:` and have `take_snapshot` read `report.agent_type` directly when bucketing by department. One-line change in the prompt; no test-plan churn (test #6 still asserts the same behavior).

---

## Nits

### AD-539d — Specify dept-object unwrap pattern

`_resolve_department` returns `str` per the spec, but the prompt doesn't document the `dept.department_id if hasattr(dept, 'department_id') else str(dept)` unwrap idiom (dreaming.py:1099). Builder may store the object directly, producing `<DepartmentName: ...>` strings in the snapshot's `by_department` dict. Add a one-liner in the docstring: *"Unwraps via `.department_id` attribute when present; falls back to `str(dept)`."*

### AD-539c — `proposed_action_for` silent fall-through for knowledge gap with empty qualification_path

Mapping rules: `knowledge + qualification_path_id != ""` → `trigger_qualification`; everything else for `gap_type=="knowledge"` falls through to `no_action`. A knowledge gap *without* a qualification path is observationally invisible — same return value as an unrecognized gap_type. Consider adding a `knowledge_no_path` sentinel to the action enum so test #9 covers both fall-through cases distinctly. Optional; affects only future observability of this surface.

---

## Verified (on this pass)

### Verify-First — per-child grep evidence

| Claim | Verified at | Live status |
|---|---|---|
| `GapReport` dataclass at `gap_predictor.py:186` | `gap_predictor.py:186` | ✅ class defined line 186-208 |
| `GapReport.affected_intent_types: list[str]` | `gap_predictor.py:196` | ✅ |
| `GapReport.qualification_path_id: str` | `gap_predictor.py:201` | ✅ |
| `GapReport.priority: str` | `gap_predictor.py:202` | ✅ |
| `GapReport.gap_type: str` | `gap_predictor.py:191` | ✅ |
| `GapReport.agent_id: str` | `gap_predictor.py:189` | ✅ |
| `GapReport.agent_type: str` | `gap_predictor.py:194` (used by AD-539d Recommended above) | ✅ |
| `detect_gaps(...)` callable used at `dreaming.py:1098` | `dreaming.py:1098` | ✅ exact line match |
| `runtime.ontology.get_agent_department(agent_type)` pattern | `proactive.py:2380`, `dreaming.py:1098` | ✅ shipped pattern; AD-539d should match |
| `_wire_<feature>` sync def + `if _wire_X(...): ...` invocation | `finalize.py:80,105,297,300` | ✅ both children's wiring matches |
| `SystemConfig.gap_pipeline_extensions` does not exist | grep `gap_pipeline_extensions` in `startup/finalize.py` → 0 | ✅ legitimate Pydantic introduction (Wave 5 convention #1 FP, documented in Wave 20 dispatch) |

### Section 0 EventType collision check

```
grep -n "GAP_REMEDIATION_RECORDED\|FLEET_GAP_SNAPSHOT_TAKEN" src/probos/events.py
  (no matches)
```
Both new event names are collision-free against post-Wave-19 `events.py` (verified against existing `GAP_IDENTIFIED` line 132, `CAPABILITY_GAP_PREDICTED` line 73, `NOTIFICATION_SNAPSHOT` line 107, `OBSERVABILITY_SNAPSHOT_PUBLISHED` line 226).

### Observational discipline

- **AD-539c:** `record_candidate` body is observational — appends to ring + emits event. `proposed_action_for` is a pure deterministic mapping. No call sites referenced for `start_qualification` or any active-remediation entry point. ✅ No scope creep.
- **AD-539d:** `take_snapshot`, `_count_by_field`, `_top_intents`, `_resolve_department` are all read-only over the supplied `gap_reports` iterable. No `runtime.federation_bridge`, no `runtime.federation_router`, no transport reads. ✅ Local-ship only.

### Privacy invariant on AD-539d snapshot payload

`FleetGapSnapshot` fields: `snapshot_at: float`, `total_gaps: int`, `by_gap_type: dict[str, int]`, `by_priority: dict[str, int]`, `by_department: dict[str, int]`, `top_intents: tuple[tuple[str, int], ...]`.

No `agent_id`, no `agent_ids`, no per-agent collection. All groupings collapse to counts. Test #10 (`test_take_snapshot_payload_excludes_agent_ids`) explicitly enforces the invariant. ✅

### Public-attribute discipline

`runtime.gap_remediation_tracker` and `runtime.gap_aggregator` — neither has a leading underscore. Wiring functions use the AD-525/AD-530 sync `_wire_<feature>` pattern with `if _wire_X(): ...` invocation. ✅

### Standing-conventions audit (Wave 5/5-7/8/9 retrospective)

| # | Convention | Status |
|---|---|---|
| 1 | Pydantic config additions are legitimate "phantom" via prompt | ✅ `GapPipelineExtensionsConfig` + `SystemConfig.gap_pipeline_extensions` declared in prompt (documented FP in pre-check) |
| 2 | New EventTypes documented in Section 0 | ✅ Section 0 lists both with child + purpose |
| 3 | Default-True only on additive observational features | ✅ Both flags default `True`; observational read-only — no breaking change |
| 4 | "What This Does NOT Change" present | ✅ Lines 374-381 |
| 5 | Hard-stops enumerated | ✅ 5 hard-stops listed |
| 6 | Per-child verify-first | ✅ 4-block grep at lines 354-371 |
| 7 | Frozen dataclass field ordering | ✅ Both dataclasses have all-defaulted-or-all-non-defaulted ordering |
| 8 | No bare mutable defaults | ✅ No mutable defaults on dataclasses; Pydantic uses `Field(default_factory=...)` implicitly via primitive types |
| 9 | No `getattr` defensive guards on intra-prompt APIs | ✅ Only used on `config.gap_pipeline_extensions` (legitimate cross-config probe) |
| 10 | No `hasattr` cross-module wiring | ✅ `emit_event` uses sibling late-bind setter pattern (AD-456/AD-530) |
| 11 | Constructor docstring/body consistency | ✅ Bodies are TBD-by-builder but docstrings + Side effects sections are coherent |
| 12 | Ring buffer / bounded history | ✅ AD-539c `_max_history = 100`; eviction documented |
| 13 | Test plan boundary coverage (happy + error + empty) | ✅ AD-539d test #2 covers empty; AD-539c test #5 covers eviction |
| 14 | Aggressive pre-deferral of grandchildren | ✅ AD-539c-i + AD-539d-i explicitly deferred with forcing functions |
| 15 | Tolerance: 1 ⚠️ on highest-risk child | ✅ 0 Required across both children; well within budget |
| 16 | File conflict sequencing | ✅ "Inter-Child File Conflict Sequencing" section documents disjoint files |
| 17 | Single combined commit | ✅ `Combo D: AD-539c + AD-539d gap pipeline extensions (observational v1)` |
| 18 | Tracker single-update | ✅ DECISIONS.md single Era V entry; PROGRESS.md single entry |
| 19 | GH issue closure list | ✅ #106 + #107 explicit |
| 20 | Async/sync clarity | ✅ Both helpers sync (no `async def`); no `await` in test plans |
| 21 | Public attribute (no leading underscore) | ✅ Verified above |
| 22 | Sibling late-bind `emit_event` setter | ✅ Both classes accept `self.emit_event = runtime.emit_event` post-construction |
| 23 | Verify-first grep evidence in prompt footer | ✅ "Verified Against Codebase" block present at line 354 |

All 23 conventions satisfied.

---

## Hard-Stop Audit

| Hard-stop | Result |
|---|---|
| Phantom API beyond pre-check's documented FP | ✅ None. Only documented FP is `SystemConfig.gap_pipeline_extensions` (legitimate Pydantic introduction). |
| AD-539c smuggles in active remediation | ✅ No. `record_candidate` only appends + emits; `proposed_action_for` is pure mapping. No `start_qualification`, `trigger_qualification_if_needed`, or qualification service calls. |
| AD-539d smuggles in federation | ✅ No. No `runtime.federation_*` reads. Helpers operate on supplied `gap_reports` iterable + `runtime.ontology` only. |
| EventType collision | ✅ No. Both names absent from `events.py`. |
| GapReport field-name drift | ✅ No. All asserted field names (`affected_intent_types`, `qualification_path_id`, `priority`, `gap_type`, `agent_id`, `agent_type`) match `gap_predictor.py:186-208`. |
| Privacy regression on AD-539d snapshot payload | ✅ No. Snapshot has counts only; test #10 enforces. |

---

## Top failure modes (anticipated)

1. **AD-539d `_resolve_department` signature** (Recommended above) — if Builder takes the prompt literally with `agent_id`, will need a registry detour. Cheap fix in revision pass, but not a blocker — defensive `_resolve_department` returns empty string on failure, so worst case is `by_department: {"": N}`.
2. **`proposed_action_for` knowledge-no-path silent fall-through** (Nit) — observational hole, not a correctness bug.

Neither failure mode reaches the hard-stop bar. Proceed to revision pass; both items can be folded into a single revision commit or deferred to grandchild ADs at Builder/Captain discretion.

---

## Re-review

_To be appended on Pass 2._
