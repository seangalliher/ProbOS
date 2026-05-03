# Wave 9B Review Pass 1 — Sweep Summary

**Reviewer:** Architect
**Date:** 2026-05-02
**Pass:** 1 of 2
**Prompts reviewed:** 2 (AD-641c, AD-641e)
**Order:** AD-641e → AD-641c (per dispatch — smallest blast radius first).

## Verdict Table

| # | Prompt | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|---|
| 1 | [`ad-641e-learned-shortcut-abstraction.md`](../ad-641e-learned-shortcut-abstraction.md) → [review](ad-641e-learned-shortcut-abstraction-review.md) | ✅ Approved | 0 | 3 | 3 |
| 2 | [`ad-641c-ward-room-thread-priority.md`](../ad-641c-ward-room-thread-priority.md) → [review](ad-641c-ward-room-thread-priority-review.md) | ❌ Not Ready | 5 | 4 | 3 |
| | **Totals** | **1 ✅ / 0 ⚠️ / 1 ❌** | **5** | **7** | **6** |

## Tolerance accounting (convention #15, relaxed)

Tolerance reservation: 1 ⚠️ allowed on highest-risk prompt only. **Not consumed** — the highest-risk prompt (641c) lands ❌ rather than ⚠️ because three critical structural defects exceed the ⚠️-grade threshold.

## Hard-Stop Triggered

**Item #1 from the dispatch hard-stop list — phantom API in prompt body the prompt does NOT itself introduce.**

`AD-641c` Section 3 `_count_endorsements`:
```python
entries = event_log.query(event_type=EventType.WARD_ROOM_ENDORSEMENT.value, limit=200)
```
`EventLog.query`'s actual parameters are `(category, agent_id, limit)` (verified at `src/probos/substrate/event_log.py:132-137`). The kwarg `event_type=` is phantom on this method. The intended surface is `query_structured(event=...)` at `event_log.py:170-176`. This is the **identical** pattern that Wave 9A pass-2 repaired on AD-641a's `query_structured(event=...)` slip — the lesson did not propagate into 641c's draft.

**Disposition:** Surfaced in 641c review as Required R1; revision pass MUST repair before pass-2 review can converge to ✅. Not a wave-blocker (revision is mechanical), but per dispatch instruction, surfaced explicitly here.

## Top Failure Modes (this sweep)

### Pattern: Wave 9A's three structural defects reproduced in AD-641c

The dispatch explicitly warned: "Wave 9A's revision pass caught 3 structural defects beyond the review (async/sync mismatch, wrong param names, wrong row shape). Apply the same architect-discretion verify-first repair posture during pass-1 review for 9B."

All three classes appear in AD-641c:

| Wave 9A 641a defect (pass-2 repair) | AD-641c counterpart (pass-1 finding) |
|---|---|
| `take_snapshot` async called from sync caller | `_count_endorsements` is sync but calls async `query` (R2) |
| `query_structured(event_type=...)` — wrong kwarg | `query(event_type=...)` — wrong kwarg AND wrong method (R1) |
| `entry.payload` — wrong row shape | `entry.payload` — same wrong row shape (R3) |

**Lesson:** the pass-2 retrospective on Wave 9A flagged these three classes for explicit greps in future review checklists. That guidance was not encoded into AD-641c's draft. Recommendation for Wave 9C onward: dispatch should ship a verify-first checklist supplement listing these three classes and requiring grep evidence in the VAC footer for each `await event_log.X(...)` and `event_log.X(...)` call.

### Pattern: live API shape vs assumed shape

Two additional structural defects in AD-641c are not Wave 9A repeats but are the same root cause — **drafting from memory rather than from grep evidence**:

| Defect | Live shape | Assumed shape | Impact |
|---|---|---|---|
| `get_thread()` returns `{"thread": ..., "posts": roots, "total_post_count": ...}` where `roots` is a tree | flat post list | 3 of 4 priority factors run on root posts only, missing all replies (R4) |
| Post dicts inside `roots` have keys `{id, thread_id, parent_id, author_id, body, created_at, edited_at, deleted, delete_reason, deleted_by, net_score, author_callsign, children}` | post dict has `department` field | cross-department factor structurally inert (R5) |

**Lesson:** `get_thread`'s tree-vs-flat shape and the absence of `department` from post rows are non-obvious. The first is an architectural choice (`children` nesting); the second is by design (department is per-author and resolved via `_resolve_author_department(author_id)`, not stored per-post). Future sub-AD prompts that consume ward_room data should grep `threads.py` line ranges around `get_thread` and `_resolve_author_department` and document both shapes in the VAC footer.

## Cross-Cutting Surface Audit

Per verification point #2: confirm no cross-prompt or Wave 9A artifact conflicts.

### Source files modified per prompt

| Prompt | New files | Modified files (append-only) |
|---|---|---|
| 641e | `src/probos/cognitive/learned_shortcuts/{__init__,protocol,workflow_cache_adapter,registry}.py`, `tests/test_ad641e_learned_shortcuts.py` | `events.py`, `config.py`, `startup/finalize.py` |
| 641c | `src/probos/cognitive/thread_priority/{__init__,scorer,service}.py`, `tests/test_ad641c_thread_priority.py` | `events.py`, `config.py`, `startup/finalize.py` |

### Conflict scan results

- **641c vs 641e:** Same triplet (events.py / config.py / finalize.py) gets two append-blocks. Each block introduces distinct EventTypes (THREAD_PRIORITY_SCORED vs LEARNED_SHORTCUT_REGISTERED+HIT), distinct Pydantic models (ThreadPriorityConfig vs LearnedShortcutsConfig), distinct finalize blocks. No textual overlap; resolution is mechanical sequential append. **No conflict.**
- **641c+641e vs Wave 9A commits (4476091, a56b6c6, f8e12ea):** Wave 9A added 5 events at `events.py:225-229`, 3 finalize blocks at `finalize.py:728-784`, 3 Pydantic models. 641c+641e append after the most-recent Wave 9A block in each file. **No conflict.**
- **EventType collisions:** Wave 9A's 5 names + 641c's 1 + 641e's 2 are pairwise distinct. **No collision.**

## Verification Point Audit

Per dispatch's 5 high-priority verification points:

| # | Point | 641e | 641c |
|---|---|---|---|
| 1 | No hidden listener dependency | ✅ zero matches | ✅ zero matches |
| 2 | No cross-cutting conflicts | ✅ clean | ✅ clean |
| 3 | VAC footer grep evidence | ✅ all claims grep-confirmed | ❌ VAC missed `event_log.query` signature → R1+R2+R3 |
| 4 | Section 0 EventType collisions | ✅ no collisions (2 new) | ✅ no collisions (1 new) |
| 5 | Aggressive pre-deferral (#14) applied | ✅ 3-of-6 ship; 3 deferred | ⚠️ advertises 4-of-7 but 2 silently inert; after R5 either becomes 4-of-7 honest or 3-of-7 with explicit defer |

## Phantom-API Pre-check Re-run Note

Wave 8.5's pre-check report (`prompts/WAVE-8.5-SPLIT-SUMMARY.md`) flagged 10 candidates across all 6 prompts; for the 9B subset:
- 641c: 1 candidate (`runtime.thread_priority_service`) — false positive (self-introduced, Section 5).
- 641e: 1 candidate (`runtime.learned_shortcut_registry`) — false positive (self-introduced, Section 6).

**The pre-check did NOT catch R1's phantom kwarg `event_type=` on `EventLog.query`** because the script scans for `runtime.X` symbol references, not for method-kwarg shapes. This is a known pre-check gap — flagged in the convention audit (#16) of the 641c review and recommended for follow-up tooling work. **Out of scope for this review.**

## Recommended Builder Order (after revision)

**641e → 641c** — same as build dispatch order. 641e is approved as-is; 641c needs revision pass and pass-2 ✅ before build. If revision converges cleanly (anticipated, given Wave 9A 641a precedent), pass-2 should land both at ✅ and the wave proceeds in dispatch order.

## Convergence Outlook for Pass 2

| Prompt | Pass-1 | Forecast for Pass-2 |
|---|---|---|
| 641e | ✅ | ✅ (no revision required; R1-R3 + N1-N3 are quality nudges) |
| 641c | ❌ | ✅ if R1-R5 applied and VAC footer updated to reflect `query_structured(event=...)`, `entry["data"]`, tree flattening, and department-resolution path |

**Convergence target for pass-2: 2 ✅ / 0 ⚠️ / 0 ❌.**

## Pattern Lessons (cross-wave)

1. **Verify-first checklists must explicitly enumerate prior-wave defect classes.** Wave 9A pass-2's three structural defects (async/sync, kwarg, row shape) were a once-removed lesson — the lesson surfaced in the retrospective but did not propagate into the 641c draft. Future dispatches should attach a "prior-wave defect class checklist" requiring grep evidence per class.
2. **Phantom-API pre-check has a method-kwarg blind spot.** The current script scans symbol references; it does not parse method calls and validate kwargs against the live signature. Extending it would have caught R1 mechanically. Recommend deferring this tooling work to a future AD; not a 9B blocker.
3. **API shape grep is mandatory for any consumer prompt.** AD-641c reads three live APIs (`event_log.query`, `ward_room.get_thread`, post dicts). Each was assumed rather than greped. The 641e prompt did the work (greps the 3 WorkflowCache method signatures explicitly in its VAC) and landed ✅; the 641c prompt skipped the second-order grep on `get_thread`'s return shape and the post dict keys, and reproduced the Wave 9A defect class. The discipline is procedurally enforceable: every API the prompt calls gets a separate VAC grep with the actual return shape captured.
