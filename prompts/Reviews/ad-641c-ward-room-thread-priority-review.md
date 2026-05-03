# Review: AD-641c — Ward Room Thread Priority (Importance Scoring Parallel to Attention Manager, v1)

**Reviewer:** Architect
**Date:** 2026-05-02
**Pass:** 1 of 2
**Verdict:** ❌ Not Ready

One-line headline: Three Wave-9A-class structural defects reproduced in `_count_endorsements` (async/sync mismatch, phantom kwarg `event_type=` on `EventLog.query`, wrong row-shape `payload` vs `data`) plus two factor-shape mismatches against the live ward_room API (`get_thread` returns a tree, not a flat post list; posts dicts have no `department` key). Two of the four advertised v1 priority factors silently report 0 against production data — no-theater violation.

Per dispatch hard-stop list item #1 (phantom API the prompt does not introduce), the `event_type=` kwarg is the canonical hard-stop and is surfaced here.

---

## Required (must fix before building)

R1. **Phantom kwarg on `EventLog.query` — hard-stop per dispatch §"phantom API not introduced by the prompt itself."**

   Section 3 `_count_endorsements`:
   ```python
   entries = event_log.query(
       event_type=EventType.WARD_ROOM_ENDORSEMENT.value, limit=200,
   )
   ```
   The actual signature at `src/probos/substrate/event_log.py:132-137` is:
   ```python
   async def query(
       self,
       category: str | None = None,
       agent_id: str | None = None,
       limit: int = 100,
   ) -> list[dict]:
   ```
   `event_type` is **not** a parameter. The correct surface is `query_structured(event=...)` at `event_log.py:170-176`:
   ```python
   async def query_structured(
       self, *, correlation_id=None, category=None, event=None,
       parent_event_id=None, limit=100,
   ) -> list[dict]:
   ```
   Replace the call with:
   ```python
   entries = await event_log.query_structured(
       event=EventType.WARD_ROOM_ENDORSEMENT.value, limit=200,
   )
   ```
   This is the **identical** repair Wave 9A pass-2 applied to AD-641a's `query_structured(event=...)` slip. Same root cause: prompt drafted from memory rather than against a `grep -n "def query" event_log.py` evidence line.

R2. **Async/sync mismatch — `_count_endorsements` is `def` but calls `async def query(...)`.**

   `EventLog.query` and `EventLog.query_structured` are both `async`. The current `_count_endorsements` is synchronous (`def _count_endorsements(self, thread_id: str) -> int:`). Calling an async method without `await` returns an unawaited coroutine, never iterates. The `for entry in entries or []:` loop fails (coroutines are not iterable, raises `TypeError: 'coroutine' object is not iterable`).

   Fix: convert `_count_endorsements` to `async def` and have `_build_input` `await` it. Cascade: `_build_input` is already async, so `await self._count_endorsements(thread_id)` is a one-line propagation.

   This is **identical** to Wave 9A pass-2's `take_snapshot` async/sync repair on AD-641a. Same pattern, missed in pass-1 there too. The Wave 9A pattern lesson explicitly called out: "Future review checklists should explicitly grep async/sync signatures and parameter names of any method called via `await` in a prompt." This review is the application of that lesson.

R3. **Wrong row shape — `EventLog.query*` returns dicts with key `data`, not `payload`.**

   `event_log.py:166` (and 215) returns `rows.append(self._row_to_dict(row))`. The row dict has keys `id, timestamp, category, event, agent_id, agent_type, pool, detail, correlation_id, parent_event_id, data` — payload data lives under `"data"`, not `"payload"`. The prompt's `_count_endorsements` does:
   ```python
   payload = getattr(entry, "payload", None) or (
       entry.get("payload") if isinstance(entry, dict) else None
   ) or {}
   ```
   Both branches return `None` against the real shape; `payload.get("thread_id")` always errors on `None.get(...)` — actually the `or {}` saves it from raising, so it silently always returns `count == 0`. The factor is dead.

   Fix:
   ```python
   data = entry.get("data") if isinstance(entry, dict) else {}
   if not isinstance(data, dict):
       data = {}
   if str(data.get("thread_id") or "") == str(thread_id):
       count += 1
   ```
   This is **identical** to Wave 9A pass-2's row-shape repair on AD-641a (rows are dicts with `data` key, not objects with `.payload`).

R4. **`get_thread` returns a tree of root posts (with nested `children`), not a flat post list.**

   Verified at `src/probos/ward_room/threads.py:728`:
   ```python
   return {"thread": thread_dict, "posts": roots, "total_post_count": total_post_count}
   ```
   where `roots` is the list of posts whose `parent_id` is None or not in the thread, with all reply posts nested under `children`. The prompt's `_extract_posts(thread)` reads `thread.get("posts")` and treats them as flat — for any threaded discussion, **all reply posts are missed**. Captain involvement, recency, and unresolved-question detection all run on roots only.

   Two acceptable fixes:
   - **(a) Use `get_thread_posts_temporal(thread_id)`** at `threads.py:750` which returns a flat ordered list. This is a `WardRoomService` API; verify whether it's exposed via the service facade or only on `_threads`. If only on `_threads`, this requires reaching into a private attribute (Demeter violation) — not preferred.
   - **(b) Recursively flatten `roots → children → ...` in `_extract_posts`.** Add a 6-line helper that walks the tree. Preserves the v1 design.

   Recommend (b). The fix is mechanical and stays within the prompt's existing ownership boundaries.

R5. **Posts dicts have no `department` field — cross-department factor is structurally inert.**

   Verified at `threads.py:711-720` (post row dict construction inside `get_thread`):
   ```python
   posts.append({
       "id": ..., "thread_id": ..., "parent_id": ..., "author_id": ...,
       "body": ..., "created_at": ..., "edited_at": ..., "deleted": ...,
       "delete_reason": ..., "deleted_by": ..., "net_score": ..., "author_callsign": ...,
       "children": [],
   })
   ```
   No `department` key. The prompt's `_build_input` does:
   ```python
   dept = str(p.get("department") or "")
   if dept:
       participants.append(dept)
   ```
   `p.get("department")` is always `None`, `participants` is always `[]`, `cross_department` factor never fires. The prompt advertises this as one of 4 v1 factors — **no-theater violation**.

   Two acceptable fixes:
   - **(a) Resolve department per post via `_resolve_author_department(author_id)`** at `threads.py:223-226` (existing helper). Adds one import + one map call per post in `_extract_posts`. Preserves the factor.
   - **(b) Defer cross-department factor to a grandchild AD** (e.g., AD-641c-iv: cross-department factor wiring). Update Solution Overview to ship 3 of 7 capabilities in v1 (matches convention #14's aggressive pre-deferral pattern).

   Either is acceptable; (a) keeps the v1 promise; (b) is the cleaner no-theater move per Wave 9A 641b's listener-defer precedent.

---

## Recommended

R6. **Sync the VAC footer with the actual `get_thread` shape.** The current footer says:
   > `(returns nested dict with "posts" key)`

   Strengthen to:
   > `(returns {"thread": dict, "posts": list[root_post_dict_with_children], "total_post_count": int}; root posts have nested "children" lists — see threads.py:716-728)`

   Documents the tree-vs-flat shape so future revisions don't slip into the same defect.

R7. **Add a regression assertion that the cross-department factor actually fires.** Test #7 (`test_cross_department_requires_two_distinct`) tests the **scorer** in isolation with a hand-built `ThreadPriorityInput`. Add a `test_service_extracts_distinct_departments_from_posts` that runs `_build_input` against a stub thread with two posts from distinct departments and asserts `inp.participant_departments` contains both. Without this, the R5 silent-zero behavior would re-emerge if a future caller drops department resolution.

R8. **Add a regression assertion that `_count_endorsements` actually counts.** Same shape as R7 but for endorsements: stub `runtime.event_log.query_structured` to return 3 endorsement rows for the target thread + 2 for a sibling thread; assert count == 3. Currently test #14 (`test_count_endorsements_filters_by_thread_id`) is named — make sure its arrange uses the corrected (R1+R3) row shape so it would have caught the original defect.

R9. **Document the `kwargs.get('post_limit', N)` flexibility on `WardRoomService.get_thread`.** The service signature at `service.py:368` is `async def get_thread(self, thread_id: str, **kwargs: Any) -> dict[str, Any] | None:` — kwargs splat. The prompt calls `await ward_room.get_thread(thread_id, post_limit=10)`. Currently this propagates through to `ThreadManager.get_thread(thread_id, post_limit=10)` at `threads.py:688`. This works **today**, but the splat is fragile (any future kwarg-name change to `ThreadManager` would silently break the service). Either: (a) ride the existing splat (current); (b) recommend explicit propagation in a follow-up cleanup AD. Mention this in `What This Does NOT Change` as a known soft-coupling.

---

## Nits

- N1. `time.time()` in `_recency_factor` introduces a non-determinism in tests. Consider injecting a `_now: Callable[[], float] = time.time` constructor parameter on `ThreadPriorityScorer` so tests can freeze the clock. The recency test at #8 will need this anyway to assert "0s ago = 1.0". Without injection, the test is flaky-prone (small machine-load variance can shift the score by `exp(-epsilon)`).
- N2. `_endorsement_factor` formula in the docstring (`0 -> 0.0, 1 -> 0.5, 5 -> ~0.92, 10 -> ~0.99`) is correct for `1.0 - exp(-0.5 * count)` only when `count` is integer-cast at entry; Section 2 has `if count <= 0: return 0.0` which handles negative/None. Good. But add a comment that `0.5 * 1 = 0.5` derivation matches the docstring (`1.0 - exp(-0.5) ≈ 0.393`, not `0.5`). Math: `1 - e^{-0.5} = 0.3935`. The docstring says 0.5. **Either the docstring is wrong or the formula is.** Recommend halving the rate (`1.0 - exp(-1.0 * count)` gives `0 → 0`, `1 → 0.632`, `2 → 0.864`) or accept the corrected docstring values. Reviewer's read: docstring values were intent; formula needs `-1.0` not `-0.5`. Bumps a Nit because this is a single-line correction in code-or-docstring; not a blocker.
- N3. Section 6 test count says ~14 named tests; Section 7 enumerates exactly 14. Acceptance criteria asks "14/14 focused tests pass" which matches. Good.

---

## Architect-Discretion Verify-First Sweep (per dispatch instruction)

The dispatch explicitly stated: "Wave 9A's revision pass caught 3 structural defects beyond the review (async/sync mismatch, wrong param names, wrong row shape). Apply the same architect-discretion verify-first repair posture during pass-1 review for 9B — if you spot a structural defect not flagged in any tier, document it explicitly."

**All three Wave 9A defect classes are reproduced in AD-641c.** Mapping:

| Wave 9A 641a defect | AD-641c counterpart | Fix |
|---|---|---|
| Async `take_snapshot` called sync | `_count_endorsements` is sync, calls async `query`. R2. | Promote method to `async def`; `await` from caller. |
| Wrong kwarg `query(event_type=...)` | Wrong kwarg `event_type=...` on `EventLog.query`. R1. | Use `query_structured(event=...)`. |
| Wrong row shape `.payload` vs `data` | Same wrong row shape. R3. | Use `entry["data"]`. |

Plus two new structural defects specific to ward_room:

| New 641c defect | Severity | Fix |
|---|---|---|
| `get_thread` returns tree not flat | Critical (3 of 4 factors degraded) | Recursively flatten OR use `get_thread_posts_temporal`. R4. |
| Posts dicts lack `department` key | Critical (cross-department factor dead) | Resolve via `_resolve_author_department(author_id)` OR defer factor. R5. |

---

## Verified Against Codebase (2026-05-02)

```
grep -n "async def query\|async def query_structured" src/probos/substrate/event_log.py
  src/probos/substrate/event_log.py:132  async def query(
  src/probos/substrate/event_log.py:170  async def query_structured(
  (both async; query takes category/agent_id/limit; query_structured takes event=)

grep -n "rows.append(self._row_to_dict\|return {\"thread\"" src/probos/substrate/event_log.py src/probos/ward_room/threads.py
  src/probos/substrate/event_log.py:166  rows.append(self._row_to_dict(row))
  src/probos/substrate/event_log.py:215  rows.append(self._row_to_dict(row))
  src/probos/ward_room/threads.py:728   return {"thread": thread_dict, "posts": roots, "total_post_count": total_post_count}

grep -n "data\":\|payload" src/probos/substrate/event_log.py | head
  (rows return key "data"; "payload" not present)

grep -n "class WardRoomService\|async def list_threads\|async def get_thread\|async def create_thread" src/probos/ward_room/service.py
  src/probos/ward_room/service.py:29   class WardRoomService(EventEmitterMixin):
  src/probos/ward_room/service.py:289  async def list_threads(self, channel_id, limit=50, offset=0, sort="recent", include_archived=False)
  src/probos/ward_room/service.py:357  async def create_thread(...)
  src/probos/ward_room/service.py:368  async def get_thread(self, thread_id: str, **kwargs: Any) -> dict[str, Any] | None:

grep -n "async def get_thread\|async def list_threads\|class ThreadManager" src/probos/ward_room/threads.py
  src/probos/ward_room/threads.py:138  class ThreadManager:
  src/probos/ward_room/threads.py:232  async def list_threads(...)
  src/probos/ward_room/threads.py:688  async def get_thread(self, thread_id: str, *, post_limit: int = 100) -> dict[str, Any] | None:
  src/probos/ward_room/threads.py:750  async def get_thread_posts_temporal(self, thread_id: str) -> list[dict[str, Any]]:

grep -n "_resolve_author_department\|resolve_author_department" src/probos/ward_room/threads.py src/probos/ward_room/_helpers.py
  src/probos/ward_room/threads.py:223  def _resolve_author_department(author_id: str) -> str:
  src/probos/ward_room/threads.py:225  from probos.ward_room._helpers import resolve_author_department

grep -n "WARD_ROOM_ENDORSEMENT\b" src/probos/events.py
  src/probos/events.py:69  WARD_ROOM_ENDORSEMENT = "ward_room_endorsement"

grep -n "class AttentionManager" src/probos/cognitive/attention.py
  src/probos/cognitive/attention.py:24  class AttentionManager:

grep -n "THREAD_PRIORITY_SCORED" src/probos/events.py
  (no matches; introduced by this prompt — no collision with Wave 9A's 5 events at events.py:225-229)

grep -n "listener|EndorsementListener|handle_event|ward_room_endorsement_listener" prompts/ad-641c-ward-room-thread-priority.md
  (zero matches — confirms no hidden dependency on the deferred WardRoomEndorsementListener)

Cross-prompt source-file conflict scan (AD-641c vs AD-641e):
  641c new files (3): src/probos/cognitive/thread_priority/__init__.py, scorer.py, service.py
                      tests/test_ad641c_thread_priority.py
  641c modified files (3): src/probos/events.py (Section 0, append),
                           src/probos/config.py (Section 4, append),
                           src/probos/startup/finalize.py (Section 5, append)
  Three-way append against same triplet shared with 641e. Each prompt's content is anchored
  content-wise at distinct EventTypes/Pydantic classes/finalize blocks. No textual overlap.

Cross-conflict with Wave 9A commits (4476091, a56b6c6, f8e12ea):
  - events.py: Wave 9A added 5 types at 225-229; 641c's 1 new type appends after 229. No overlap.
  - finalize.py: Wave 9A added blocks at 728-784 (ObservabilityBridge / WardRoomHebbianRouter /
    EngineeringSensorService). 641c appends after the most-recent block. No overlap.
  - config.py: Wave 9A added 3 Pydantic models. 641c adds ThreadPriorityConfig. No overlap.
  No cross-conflict.
```

---

## Convention Audit (19 standing conventions)

| Conv | Application |
|---|---|
| #1 Public-attribute wiring | ✅ `runtime.thread_priority_service` public. |
| #2 stdlib persistence | ✅ no persistence in v1. |
| #3 Coordinator-first dispatch-deferred | ⚠️ Service ships, but R4+R5 mean 2 of 4 v1 factors silently zero — ships theater. Required findings repair this. |
| #4 Superset filter discipline | n/a |
| #5 startup `emit_event_fn` | ✅ Section 5 uses `runtime.emit_event`. |
| #6 Verify-first | ❌ R1+R2+R3 are concrete verify-first failures: VAC footer claims `event_log.query()` exists but did not grep the signature. Conv #6 explicitly violated. |
| #7 No theater | ❌ R4+R5: two factors structurally inert against live data shape. Cross-department + endorsement_density both report 0 in production. |
| #8 TYPE_CHECKING cross-layer | n/a |
| #9 ASCII-only comments | ✅ |
| #10 work_item_store vs workforce | n/a |
| #11 `__new__`-bypass `getattr` | ✅ `getattr(self._runtime, "ward_room", None)` and similar throughout. |
| #12 Solution Overview drift | ⚠️ Solution Overview says "4 priority factors wired"; in practice 2 fire, 2 silently zero. Drift between prose claim and runtime behavior. |
| #13 Pool template name collision | n/a |
| #14 Aggressive pre-deferral | ✅ ships 4 of 7; defers 3. (After R5(b) deferral, ships 3 of 7.) |
| #15 Relaxed tolerance | ❌ Verdict cannot land at ⚠️ — multiple critical structural defects exceed tolerance reservation. |
| #16 Phantom-API pre-check | ⚠️ Pre-check (Wave 8.5) cleared `runtime.thread_priority_service` (self-introduced). Did NOT catch the `event_log.query(event_type=...)` phantom kwarg because the script scans `runtime.X` symbol references, not method-kwarg shapes. Recommend extending pre-check to flag method-kwarg phantoms (out of scope for this review). |
| #17 Per-instance mutable state in `__init__` | ✅ |
| #18 Mock all attributes the code reads | ⚠️ Test plan uses `AsyncMock(spec=WardRoomService)` for `ward_room`, but does not specify the mock for `event_log.query_structured` (after R1 fix). After R1+R2, test #11 must mock the async method. Recommend extending test plan. |
| #19 Session-id in headers | n/a |

**Conventions failed: #6, #7, #15. Drift: #3, #12. Mock gap: #18.**

---

## Disposition

AD-641c is **not ready for build**. Three structural defects in `_count_endorsements` are exactly the same Wave 9A pattern (async/sync mismatch + phantom kwarg + wrong row shape); two additional defects (tree-vs-flat post shape + missing `department` key on post dicts) are unique to the ward_room API surface and silently degrade two of the four advertised v1 factors. After repair, the prompt is structurally sound — the scorer is pure, the service is the right shape, the configuration / startup / event surface are clean. But the pass-1 prompt as drafted reproduces the exact set of latent live-API mismatches Wave 9A's revision pass had to repair. The dispatching architect's verify-first instruction was prescient.

The repair is well-scoped: R1+R2+R3 are ~10 lines in `_count_endorsements`; R4 is ~6 lines for tree flattening; R5 is either ~3 lines (resolve department per author) or a Solution Overview deferral edit. Total revision: ~20-25 lines plus VAC footer + Solution Overview updates. Pass-2 should converge cleanly.

Per dispatch hard-stop list item #1 ("Phantom API in a prompt body that the prompt does NOT itself introduce — surface immediately"), R1's `event_type=` kwarg on `EventLog.query` is the canonical hard-stop and is surfaced in the sweep summary.
