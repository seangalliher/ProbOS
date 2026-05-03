# Review: AD-475 — Captain's Ready Room (v1)

**Verdict:** ✅ Approved — small Recommended items only; no Required findings; convention #12 (Solution Overview drift watch) clean.

**Date:** 2026-05-02

**Headline:** TOGAF wholesale-deferral is explicit (no v1 stub); Idea Capture + 3-phase Sessions ship real work; Ward Room thread creation correctly uses verified `create_thread` signature.

---

## Required (must fix before building)

*(None.)*

---

## Recommended

1. **Section 3 `import asyncio` is unused.** Top of `sessions.py` (around line ~280 of the prompt's code block):

   ```python
   import asyncio
   ```

   The file does not call `asyncio.sleep`, `asyncio.create_task`, or any async helper directly — `await ward_room.create_thread(...)` is the only async call and doesn't need the import. **Fix:** drop the unused import. (Builder's lint pass will likely catch this; explicit is cleaner.)

2. **Section 3 `start_session` failure mode for malformed `participants`.** The prompt only validates `topic`:

   ```python
   if not topic:
       raise ValueError("start_session requires non-empty topic")
   ```

   `participants` is consumed as `list[str]` and passed to `create_thread` body string. If `participants` is a non-list (e.g., a string), `', '.join(participants)` will iterate characters. Recommend adding `if not isinstance(participants, list): raise TypeError(...)` or coercing via `list(participants)`.

3. **Test 11 phase-progression boundary.** Test name claims `"Captain or convener presents the topic" -> "discuss" -> "converge"`. The test verifies the cycle PRESENT → DISCUSS → CONVERGE → CONVERGE (terminal idempotent). Consider also testing the `advance_phase` of a non-existent session_id returns `None` (the implementation handles this correctly at line 393 — but no test covers it). Add a 13th test or fold into Test 11.

4. **`SessionPhase` enum value `"present"` collides with `WardRoomThread.thread_mode="discuss"`.** No real conflict — these are distinct enum spaces. But the visual ambiguity (both `phase` and `thread_mode` have a `"discuss"` literal) could mislead reviewers. Recommend documenting in the Solution Overview that the two `discuss` strings are independent.

5. **Section 6 finalize wiring uses `runtime.data_dir / config.ready_room.idea_store_filename`.** The default filename is `"ready_room/ideas.json"` — a path with a slash. Path concatenation works (`Path / "a/b.json"` = `Path("a/b.json")`). But the parent directory `data_dir/ready_room/` may not exist before the first `_save()`. The `_save` at `idea_store.py` line 178-180 calls `self._store_path.parent.mkdir(parents=True, exist_ok=True)` — so it self-creates. ✅. Recommend explicit comment in finalize to confirm the implicit mkdir intent.

6. **`journal_correlation_id` is set on the session but no journal write happens in v1.** The prompt explicitly notes this as honest deferral (the journal write happens at the existing decomposer/run boundary). But "exists at the existing decomposer/run boundary" is hand-wavy — recommend grepping `cognitive_journal.write` callers and citing one as the integration target for AD-475c. Without that citation, the deferred wiring is not anchored.

7. **`runtime.idea_capture_store = None` and `runtime.ready_room_session_manager = None` when disabled.** The Wave 5 always-wired pattern is followed (consumers can defensively check). ✅. But the `_=None` branch isn't tested. Recommend adding a 13th test: `test_session_manager_disabled_sets_runtime_attrs_none` (probably best at the integration test level — fine to defer to integration, but document).

---

## Nits

- **`SessionPhase` defined as `str, Enum`** — value matches `phase` field on the frozen dataclass. Conventional Python pattern. ✅
- **`Idea.tags: list[str] = field(default_factory=list)`** — correct frozen-dataclass default. ✅
- **`replace(idea, status=status)`** — frozen-dataclass mutation pattern. ✅
- **Section 0 EventType `READY_ROOM_SESSION_STARTED` and `IDEA_CAPTURED`** — free; no collisions. ✅
- **`ReadyRoomConfig.wardroom_channel_id: str = "ready_room"`** — sensible default. The channel doesn't need to pre-exist; Ward Room's `create_thread` will accept any channel_id string. ✅
- **Test plan has 12 tests; estimate said ~12.** ✅

---

## Verified (looks good)

- `WardRoomService` at `ward_room/service.py:29`. ✅
- `create_thread` signature at `ward_room/service.py:357-363` accepts `(channel_id, author_id, title, body, author_callsign="", thread_mode="discuss", max_responders=0)`. The prompt's call passes the first 5 + `thread_mode="discuss"`. ✅
- `ArchitectAgent` at `cognitive/architect.py:47`. ✅ (referenced as "unchanged" — correct).
- `runtime.ward_room` at `runtime.py:390, 1550`. ✅
- `runtime.cognitive_journal` at `runtime.py:213, 424, 1593`. ✅
- `runtime.data_dir` is the AD-468 public property. ✅
- `runtime.emit_event` at `runtime.py:785`. ✅
- New public attributes `runtime.idea_capture_store` + `runtime.ready_room_session_manager` (no leading underscore). ✅
- TOGAF Architecture Hierarchy, 5-phase discussion, Idea→Spec pipeline all wholesale-deferred at draft time per convention #14. **No v1 stub — convention #7 honored.** ✅
- 3-phase enum (PRESENT → DISCUSS → CONVERGE) is internally consistent and idempotent at terminal. ✅
- `__new__`-bypass defensive `getattr(self, "_runtime", None)` per convention #11. ✅
- HXI Solution Overview drift watch (convention #12) — Solution Overview, Dependencies, and "What This Does NOT Change" are aligned. ✅
- Stdlib-only persistence (`json.dumps` + atomic `os.replace`) per convention #2. ✅

---

## Conventions audit

| # | Rule | Status |
|---|---|---|
| 1 | Public-attribute wiring | ✅ |
| 2 | stdlib-only persistence | ✅ |
| 3 | Coordinator-then-dispatch | ✅ TOGAF + 5-phase + Idea→Spec deferred |
| 4 | Superset-filter | ✅ WardRoomService unchanged; new caller |
| 5 | init_<phase> | ✅ |
| 6 | Verify-first | ✅ |
| 7 | No-theater | ✅ TOGAF deferred WITHOUT v1 stub |
| 8 | TYPE_CHECKING + ALLOWED_EXCEPTIONS | N/A |
| 9 | ASCII-only comments | ✅ |
| 10 | work_item_store vs workforce | N/A |
| 11 | __new__-bypass defensive-getattr | ✅ |
| 12 | Solution Overview drift | ✅ (HXI surface + clean alignment) |
| 13 | Pool template name collision | N/A |
| 14 | Aggressive pre-deferral | ✅ 3 of 5 deferred |
| 15 | Tolerance: relaxed | n/a (review tier) |

---

## Bottom Line

AD-475 is the cleanest Wave 8 prompt. Recommended items are tightening only — Builder can dispatch this prompt as-is and the Recommendeds can be folded into the build report. Closest match to a first-pass-pass under relaxed tolerance.

---

## Second-Pass Review (2026-05-02)

**Verdict:** ✅ Approved (re-confirmed)

**Headline:** Recommended items folded in cleanly during revision; no regressions; first-pass ✅ verdict holds.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| (none — pass-1 verdict was ✅) | n/a | n/a |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1: drop unused asyncio import | ✅ Applied | Section 3 import block now omits `import asyncio`; only `await` keyword needed. |
| rec#2: defensive `participants` coercion | ✅ Applied | Line 354: `if not isinstance(participants, list): participants = list(participants) if participants is not None else []`. Prevents string-iterate-as-characters. |
| rec#3: extra advance_phase test (#13) | ✅ Applied | Test #13 `test_session_manager_advance_phase_returns_none_for_unknown_id` added. Test count 12 → 13. |
| rec#4: SessionPhase / thread_mode disambiguation | 📦 Deferred | Cosmetic; two `discuss` literals live in distinct namespaces. |
| rec#5: explicit comment in finalize about implicit mkdir | ✅ Applied | Section 6 now has the comment. |
| rec#6: journal_correlation_id integration target | 📦 Deferred | AD-475c picks up the journal write seam. |
| rec#7: disabled-runtime-attr None test | 📦 Deferred | Folded into integration test scope. |

### New Findings (introduced during revision)

None. The revision touched 3 spots (asyncio import, participants coercion, test #13, plus a comment in Section 6) — all safe additive changes.

### Verified Against Revised Codebase Claims

- `WardRoomService.create_thread` signature unchanged: `ward_room/service.py:357` ✅
- `runtime.ward_room` exists: `runtime.py:390, 1550` ✅
- `runtime.cognitive_journal` exists: `runtime.py:213, 424, 1593` ✅
- `runtime.emit_event` is the public method at `runtime.py:785` ✅
- TOGAF Architecture Hierarchy / 5-phase / Idea→Spec pipeline still wholesale-deferred — convention #14 + #7 honored.
- New test #13 spec is consistent with the existing line-393 `advance_phase` idempotent contract.

### Tolerance Assessment

AD-475 is the wave's "✅-on-first-pass + ✅-on-second-pass" reference prompt. No further review required pre-Builder.
