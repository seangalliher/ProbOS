# Review: AD-641e — LearnedShortcut Shared Abstraction (Protocol over WorkflowCache, v1)

**Reviewer:** Architect
**Date:** 2026-05-02
**Pass:** 1 of 2
**Verdict:** ✅ Approved

One-line headline: Clean Protocol-over-existing-class design, all concrete claims grep-verified, no hidden dependency on the deferred WardRoomEndorsementListener; 12 v1 tests cover the surface; no cross-prompt or Wave 9A artifact conflicts.

---

## Required (must fix before building)

_None._

---

## Recommended

R1. **Surface a property-vs-callable note for `WorkflowCache.size`.** `size` is a `@property` (`workflow_cache.py:115-117`, returns `len(self._cache)`). The adapter uses `int(getattr(self._cache, "size", 0) or 0)` which works correctly because `getattr` invokes property descriptors — but a future contributor seeing the `or 0` defensiveness might assume it's a method. Add a one-line comment in `workflow_cache_adapter.py` Section 3: `# WorkflowCache.size is a @property (verified at workflow_cache.py:115).` Pure cosmetic.

R2. **Test #4 should also assert `isinstance(stub, LearnedShortcutBackend)` is True for any class with the 5 Protocol members.** Section 7 covers `WorkflowCacheBackend`. Add a sibling case using a hand-rolled minimal stub class (`class _MinimalStub: kind="x"; size=0; def lookup/store/evict ...`) so the `@runtime_checkable` decorator's structural-typing contract is tested in addition to its concrete consumer. Strengthens the Open/Closed claim. Could be merged into test #4 or split as #4b.

R3. **Document the read-side fan-out rationale in Section 4.** The `lookup_first` walk-and-emit pattern is correct, but the prompt's prose claims "registry walks backends in registration order until first hit." Add an explicit sentence: "Registry does not coalesce values across backends — first hit wins; this honors design-doc 'separate stores' principle." Helps the future JIT-adapter contributor (AD-641e-i) understand the contract before writing a competing fan-out.

---

## Nits

- N1. Section 3 docstring says "AD: existing" — replace with the actual AD reference (workflow_cache landed in AD-274 / `git log --follow src/probos/cognitive/workflow_cache.py`). One-word fix.
- N2. Section 4 `lookup_first` swallows emit-event failures via bare `except Exception: pass`. This is convention-aligned (emit is non-critical observability), but a single-line `logger.debug("LearnedShortcutRegistry: emit failed", exc_info=True)` inside the except would help future BF triage. Optional.
- N3. Acceptance criteria lists "12/12 focused tests pass at -n 0" but the test plan enumerates exactly 12 named tests — consider adding a 13th regression-style test: `test_existing_workflow_cache_tests_unchanged` that imports `WorkflowCache` and asserts the public method set is `{store, lookup, lookup_fuzzy, size, ...}`. Ensures the Open/Closed claim is testable, not just asserted in prose.

---

## Architect-Discretion Verify-First Sweep (per dispatch instruction)

Wave 9A pass-2 found three latent live-API mismatches that pass-1 missed (async/sync mismatch on `take_snapshot`, wrong kwarg `event_type=` vs `event=` on `query_structured`, dict row shape `data` vs `payload`). I checked AD-641e for the same pattern classes:

| Class | Pattern | 641e status |
|---|---|---|
| Async/sync mismatch | Calling async API without await, or sync from sync | ✅ No async APIs called. `WorkflowCache.lookup/store` are sync (verified at workflow_cache.py:29, 56). |
| Wrong kwarg name | Calling `query(event_type=...)` etc. | ✅ Adapter passes positional `key`/`value` into `WorkflowCache.lookup(user_input)` and `store(user_input, dag)` — positional is signature-agnostic; works regardless of param name. |
| Wrong row/return shape | Treating dict as object or vice versa | ✅ Adapter does not unpack lookup return; passes through. Registry's `lookup_first` returns `tuple[kind, value]`, leaving value-shape opaque to caller. |
| Phantom API on existing class | Calling method that doesn't exist | ✅ `WorkflowCache.evict()` does not exist; prompt acknowledges and returns `False` (deferred to AD-641e-ii). Zero phantom calls. |

**No structural defects found.** This prompt does not rerun the Wave 9A 641a class.

---

## Verified Against Codebase (2026-05-02)

```
grep -n "class WorkflowCache\b\|def store\|def lookup\|def lookup_fuzzy\|@property\s*\n\s*def size" src/probos/cognitive/workflow_cache.py
  src/probos/cognitive/workflow_cache.py:17  class WorkflowCache:
  src/probos/cognitive/workflow_cache.py:29  def store(self, user_input: str, dag: TaskDAG) -> None:
  src/probos/cognitive/workflow_cache.py:56  def lookup(self, user_input: str) -> TaskDAG | None:
  src/probos/cognitive/workflow_cache.py:67  def lookup_fuzzy(...)
  src/probos/cognitive/workflow_cache.py:115-117 @property def size(self) -> int: return len(self._cache)

grep -n "self\.workflow_cache\|workflow_cache=self" src/probos/runtime.py
  src/probos/runtime.py:79   from probos.cognitive.workflow_cache import WorkflowCache
  src/probos/runtime.py:195  workflow_cache: WorkflowCache
  src/probos/runtime.py:351  self.workflow_cache = WorkflowCache()
  src/probos/runtime.py:356  workflow_cache=self.workflow_cache,

grep -n "def emit_event\b" src/probos/runtime.py
  src/probos/runtime.py:802  def emit_event(self, event: BaseEvent | str | EventType, data: dict[str, Any] | None = None) -> None:
  (signature accepts (EventType, dict) — matches Registry call site)

grep -rn "cognitive_jit\|CognitiveJITService\|class JITService" src/probos/
  (no matches; v1 deferral to AD-641e-i confirmed)

grep -rn "class LearnedShortcutBackend\|class LearnedShortcutRegistry\|LearnedShortcutProtocol" src/probos/
  (no matches; new module, no collision)

grep -n "LEARNED_SHORTCUT_REGISTERED\|LEARNED_SHORTCUT_HIT" src/probos/events.py
  (no matches; events introduced by this prompt; no collision with Wave 9A's 5 added types
   verified at events.py:225-229 — OBSERVABILITY_SNAPSHOT_PUBLISHED, OBSERVABILITY_BRIDGE_FAILED,
   WARD_ROOM_HEBBIAN_UPDATED, WARD_ROOM_HEBBIAN_DECAYED, ENGINEERING_SENSOR_REPORT)

grep -n "listener|EndorsementListener|handle_event|ward_room_endorsement_listener" prompts/ad-641e-learned-shortcut-abstraction.md
  (zero matches — confirms no hidden dependency on the deferred WardRoomEndorsementListener)

Cross-prompt source-file conflict scan (AD-641c vs AD-641e):
  641e new files (5): src/probos/cognitive/learned_shortcuts/__init__.py, protocol.py,
                      workflow_cache_adapter.py, registry.py
                      tests/test_ad641e_learned_shortcuts.py
  641e modified files (3): src/probos/events.py (Section 0, append),
                           src/probos/config.py (Section 5, append),
                           src/probos/startup/finalize.py (Section 6, append)
  641c modified files (3): same triplet — append-only at distinct anchors.
  Conflict risk: events.py / config.py / finalize.py three-way append. Each prompt's content
  is anchored content-wise (different classes, different EventType names, different finalize
  blocks). No textual overlap; resolution is mechanical. **No conflict.**

Cross-conflict with Wave 9A commits (4476091, a56b6c6, f8e12ea):
  - events.py: Wave 9A added 5 types at lines 225-229. 641e's 2 new types append after 229 — no overlap.
  - finalize.py: Wave 9A added blocks at lines 728-784 (ObservabilityBridge, WardRoomHebbianRouter,
    EngineeringSensorService). 641e appends after the most-recent block — no overlap.
  - config.py: Wave 9A added 3 Pydantic models. 641e adds LearnedShortcutsConfig — no overlap.
  No cross-conflict.
```

---

## Convention Audit (19 standing conventions)

| Conv | Application |
|---|---|
| #1 Public-attribute wiring | ✅ `runtime.learned_shortcut_registry` public; no leading underscore on consumer surface. |
| #2 stdlib persistence | ✅ v1 in-memory only; persistence wholesale-deferred to AD-641e-iii. |
| #3 Coordinator-first dispatch-deferred | ✅ Registry ships read-side fan-out; multi-store eviction deferred to AD-641e-ii. |
| #4 Superset filter discipline | n/a (no listener / superset) |
| #5 startup `emit_event_fn` | ✅ Section 6 finalize uses `runtime.emit_event` (consistent with Wave 9A). |
| #6 Verify-first | ✅ All claims grep-confirmed. |
| #7 No theater | ✅ `evict()` honestly returns False; JIT adapter wholesale-deferred (no fake JIT class). |
| #8 TYPE_CHECKING cross-layer | n/a (single-layer cognitive imports) |
| #9 ASCII-only comments | ✅ `<-`, `->`, `--` only. |
| #10 work_item_store vs workforce | n/a |
| #11 `__new__`-bypass `getattr` | ✅ Adapter uses `getattr(self._cache, "size", 0)` for defensiveness. |
| #12 Solution Overview drift | ✅ 3 v1 capabilities enumerated; 3 deferred grandchildren; matches Section bodies. |
| #13 Pool template name collision | n/a |
| #14 Aggressive pre-deferral | ✅ Ships 3 of 6 capabilities (Protocol, WorkflowCacheBackend, Registry). Defers JIT, cross-eviction, persistence. |
| #15 Relaxed tolerance | ✅ verdict at convergence target. |
| #16 Phantom-API pre-check | ✅ Wave 8.5 already ran; documented 1 false positive (`runtime.learned_shortcut_registry` self-introduced). |
| #17 Per-instance mutable state in `__init__` | ✅ `self._backends: list = []` initialized in `__init__`, not class attribute. |
| #18 Mock all attributes the code reads | ✅ Tests use real `WorkflowCacheBackend` wrapping a stub WorkflowCache (Protocol structural typing); no AsyncMock needed (no async APIs). |
| #19 Session-id in headers | n/a |

**Convention compliance: 19/19 (n/a or applied).**

---

## Disposition

AD-641e is approved as drafted. The Protocol-adapter-registry triple is textbook Open/Closed: existing `WorkflowCache` is unchanged, the Protocol exposes a 5-method surface, the adapter delegates, the registry coordinates without merging. Verify-first claims all grep-confirm. The async/sync, kwarg, and row-shape pattern classes that bit Wave 9A's 641a do not appear here. Three Recommended items are quality nudges, not blockers; three Nits are pure cosmetic. The prompt is build-ready as-is; if the architect wants a single revision pass, R1-R3 take ~10 lines total. The dispatch's "smaller blast radius (purely cognitive layer)" framing held up under verification.


---

## Second-Pass Review (2026-05-02)

**Verdict:** ✅ Approved

One-line: All 3 Recommended + all 3 Nits applied as documented; no scope expansion; no new structural defects; phantom-API pre-check clean.

### Resolution Audit

| Pass-1 Recommended | Status | Evidence in revised prompt |
|---|---|---|
| R1 (`size` property comment) | ✅ Applied | Section 3 adapter, lines added inside `@property def size`: comment "WorkflowCache.size is a @property (verified at workflow_cache.py:115); getattr() invokes the property descriptor, so the `or 0` is purely defensive against a None return -- it is not a method-vs-property guard." |
| R2 (minimal-stub structural-typing test) | ✅ Applied | Test #4b `test_protocol_runtime_checkable_recognizes_minimal_stub` added in Section 6 — hand-rolled stub with the 5 Protocol members. |
| R3 (read-side fan-out semantics documented) | ✅ Applied | Section 4 prelude + module docstring both state: "lookup_first() walks backends in registration order and returns the FIRST non-None hit (no merging)." Cites design-doc 'separate stores' principle. |

| Pass-1 Nits | Status | Evidence |
|---|---|---|
| N1 (replace "AD: existing" with real AD ref) | ✅ Applied | Section 3 docstring now says `AD-274; preexisting`. |
| N2 (logger.debug instead of bare `except: pass`) | ✅ Applied | Both `register()` and `lookup_first()` except-Exception blocks are `logger.debug("LearnedShortcutRegistry: emit ... failed", exc_info=True)`. |
| N3 (regression test for `WorkflowCache` public API) | ✅ Applied | Test #13 `test_existing_workflow_cache_public_api_unchanged` added; asserts `{store, lookup, lookup_fuzzy, size}` intact. |

### New Findings (introduced during revision)

1. **None of substance.** One micro-tension: Acceptance criteria reads "13/13 focused tests pass at `-n 0` (12 v1 + 1 regression guard; 4b is renumbered as #4-stub but counted in the 13)" — but Section 6 enumerates #1, #2, #3, #4, #4b, #5, #6, #7, #8, #9, #10, #11, #12, #13 = 14 tests, not 13. The Revision row N3 says "Acceptance test count updated from 12 to 13 (1 added) -- 4b is structurally a sibling of #4 but counted in the 13." This is internally consistent if 4b is treated as a *sub-case* of #4 (one parametrized test with two `isinstance` checks); it is internally inconsistent if 4b is a separate `def test_...` function. The Builder will likely treat them as separate functions because that's the cleanest reading of Section 6's enumeration (each line is a separate `def`). **Disposition:** Nit, not a blocker. Either:
   - Builder writes 14 separate test functions and the gate counts 14 — acceptance criteria's "13/13" is mildly off-by-one but the test count is monotonically increasing from baseline so the gate still passes. OR
   - Builder collapses #4 and #4b into one parametrized test — also fine.
   Surface as Nit only, no revision required. The substance (structural-typing test exists) is delivered either way.

### Pre-check

`./scripts/phantom-api-precheck.ps1 prompts/ad-641e-learned-shortcut-abstraction.md` → **0 phantom candidates**. Section 5 finalize wiring claim `runtime.learned_shortcut_registry` is self-introduced and clean.

### Wave 9A Defect-Class Sweep (architect-discretion)

| Class | 641e revised status |
|---|---|
| Async/sync mismatch | ✅ No async APIs called; `WorkflowCache.lookup/store` sync. |
| Wrong kwarg name | ✅ `WorkflowCache.lookup(user_input)` / `store(user_input, dag)` are positional; signature-agnostic. |
| Wrong row/return shape | ✅ Adapter does not unpack lookup return; passes through. |
| Phantom API on existing class | ✅ `WorkflowCache.evict()` honestly returns `False`; deferred to AD-641e-ii. |

**No structural defects in revised prompt.**

### Cross-conflict Re-scan

- Wave 9A artifacts (events.py:225-229, finalize.py:728-784, 3 Pydantic models): ✅ revised prompt's appends still anchor after the Wave 9A blocks; no overlap.
- Listener-class greps (`EndorsementListener|handle_event|ward_room_endorsement_listener`): ✅ 0 matches in revised prompt.
- 641e + 641c three-way append on (events.py / config.py / finalize.py): ✅ distinct EventTypes, distinct Pydantic models, distinct finalize blocks. Mechanical sequential append.

### Disposition

AD-641e revision is **build-ready**. The revision is purely additive (Recommended + Nits, no scope change), structurally sound, and the Open/Closed claim is now mechanically testable via #4b + #13. Build with confidence.
