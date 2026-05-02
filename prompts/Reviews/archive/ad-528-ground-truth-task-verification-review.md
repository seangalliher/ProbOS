# Review: AD-528 — Ground-Truth Task Verification (Anti-Fabrication)

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — `EpisodicMemory.store()` requires a typed `Episode` dataclass, NOT a `dict`. AD-528's `VerificationEpisodeWriter.write()` passes a raw dict — this will fail at runtime. One mechanical fix; orthogonality with AD-451 ReconciliationEscalator is well-documented.

The dispatch's high-priority verification (TYPE_CHECKING import, episode storage non-optional, no AD-451 integration) — first two have findings; third is clean.

---

## Required (must fix before building)

### 1. `EpisodicMemory.store()` requires `Episode` dataclass, not `dict`

`VerificationEpisodeWriter.write()` (Section 2 line 290+):

```python
episode: dict[str, Any] = {
    "kind": "ground_truth_verification",
    "verified": result.verified,
    ...
}
await store(episode)
```

Verified — the live `EpisodicMemory.store()` signature requires a typed `Episode`:

```
grep -n "async def store" src/probos/cognitive/episodic.py
  942: async def store(self, episode: Episode) -> None:

grep -n "class Episode" src/probos/types.py
  411: class Episode:
```

`Episode` is a frozen dataclass at `types.py:411` with required fields:

```
view src/probos/types.py:411-435

@dataclass(frozen=True)
class Episode:
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = 0.0
    user_input: str = ""
    dag_summary: dict[str, Any] = field(default_factory=dict)
    outcomes: list[dict[str, Any]] = field(default_factory=list)
    reflection: str | None = None
    agent_ids: list[str] = field(default_factory=list)
    duration_ms: float = 0.0
    embedding: list[float] = field(default_factory=list)
    shapley_values: dict[str, float] = field(default_factory=dict)
    trust_deltas: list[dict[str, Any]] = field(default_factory=list)
    source: str = "direct"
    anchors: AnchorFrame | None = None
    importance: int = 5
    correlation_id: str = ""
    valid_from: float = 0.0
    valid_until: float = 0.0
```

Inside `store()`, the storage gate at `episodic.py:951` calls `_storage_gate.evaluate(episode)` which assumes `episode.id`, `episode.agent_ids`, etc. A raw dict has none of those attributes. Build-as-written will raise `AttributeError` on the first call.

**Action:** Rewrite Section 2 `VerificationEpisodeWriter.write()` to construct a real `Episode`:

```python
from probos.types import Episode

episode = Episode(
    timestamp=time.time(),
    user_input=result.claimed_summary[:1000],  # truncate to avoid bloat
    agent_ids=[result.agent_id] if result.agent_id else [],
    dag_summary={
        "kind": "ground_truth_verification",
        "booking_id": result.booking_id,
        "verified": result.verified,
        "score": result.score,
        "signals": list(result.signals),
        "completed_at": result.completed_at,
    },
    source="ground_truth_verifier",  # AD-541 MemorySource value
    importance=7 if not result.verified else 4,  # failed verifications matter more
    correlation_id="",  # AD-492 if available; empty otherwise
)
await store(episode)
```

The `dag_summary` field is the right structured-payload home for verification metadata — it's already a `dict[str, Any]` consumed by Episode searches. The `source` field accepts a string per AD-541 MemorySource.

Verify the `MemorySource` enum has a value compatible with `"ground_truth_verifier"`, or use an existing source value like `"direct"`. Builder must grep before committing.

### 2. TYPE_CHECKING import for `BookingJournal` requires `ALLOWED_EXCEPTIONS` entry

The prompt acknowledges this in passing but doesn't spell out the `tests/test_layer_boundaries.py` ALLOWED_EXCEPTIONS edit. The Builder will hit a layer-boundary test failure (mirrors BF-085 / AD-451 precedent).

Verified — `cognitive/ground_truth.py` importing from `probos.workforce` crosses a layer boundary:

```
grep -n "ALLOWED_IMPORTS" tests/test_layer_boundaries.py
  38: ALLOWED_IMPORTS = {
  ...
  "cognitive": {"knowledge", "substrate", "mesh"},
```

`workforce.py` is a top-level module (not in any of cognitive's allowed layers).

**Action:** add a Section 7 to AD-528 explicitly instructing the Builder to add the ALLOWED_EXCEPTIONS entry:

```python
# In tests/test_layer_boundaries.py, add to ALLOWED_EXCEPTIONS:
("cognitive/ground_truth.py", "probos.workforce"),
```

With a justification comment: "AD-528: cognitive -> workforce -- TYPE_CHECKING-only type annotation for BookingJournal; runtime read goes through `runtime.workforce` public attribute injection. Mirrors BF-085 / AD-451 precedent."

### 3. `MemorySource` enum value for verification episodes — verify before claiming

The prompt's Section 2 doesn't specify what `source` value the new episode should use. AD-541 introduced `MemorySource`; valid values must be greppable. Required #1's fix proposes `source="ground_truth_verifier"` but that may not be a valid enum value.

**Action:** the Builder must grep `class MemorySource` in `src/probos/types.py` and pick an existing value (likely `"direct"` or add a new enum member). Document in the prompt that the Builder should:

1. Grep `class MemorySource` to enumerate valid values.
2. If `"ground_truth_verifier"` is not a member, either use `"direct"` (acceptable) or add a new member to the enum (substantive change — should be its own AD or a documented sub-task).

For v1 simplicity, recommend using `source="direct"`.

---

## Recommended

### 1. Section 2 `_fetch_journal()` falls back to first entry if no "working" entry

```python
for entry in entries or []:
    if getattr(entry, "journal_type", "") == "working":
        return entry
return (entries[0] if entries else None)
```

Verified — `BookingJournal.journal_type: str = "working"` is the default at `workforce.py:742`. The fallback to `entries[0]` makes sense for journals that have multiple types (e.g., "billable" followed by "working"), but it's not explicit in the docstring.

Document in the docstring: "Prefers `journal_type='working'`; falls back to first entry if none found."

### 2. `event_window_seconds = 600.0` (10 minutes) is generous; tighter window improves signal

A claim of "I just completed task X" should have an event in the audit log within seconds, not minutes. The 10-minute window is generous to handle clock skew and out-of-order events. Acceptable for v1, but document that AD-528b active rejection should tighten the window.

### 3. Score threshold semantics: `score >= self._threshold` vs `>` boundary

```python
verified = score >= self._threshold
```

Test #10 is `test_verify_threshold_boundary` — score exactly equal to threshold → verified=True. ✅ Correct semantics. Recommend the test description make explicit: "boundary is inclusive; score exactly 0.75 with threshold 0.75 verifies."

### 4. `claimed_summary` truncation in Required #1's fix

The Required #1 resolution suggests `user_input=result.claimed_summary[:1000]`. The Episode dataclass has no length cap on `user_input` directly, but episodic memory storage may have bloat issues with long summaries. 1000 chars is conservative.

Verify the existing `compute_importance` (AD-598) tolerates long `user_input`; if it does, the truncation is precautionary. Document the choice in the docstring.

### 5. AD-528 vs AD-451 orthogonality — well-documented

The dispatch flagged this as a concern. The prompt's "What This Does NOT Change" section explicitly addresses it:

> AD-451's ReconciliationEscalator (`cognitive/validation_framework.py`) is NOT integrated in v1. AD-528 and AD-451 cover orthogonal questions:
> - AD-451: which of two verifiers do we trust on the same outcome?
> - AD-528: did the action happen at all?

Clear and correct. ✅ A future AD-528b may emit a `VerificationResult` ReconciliationEscalator can ingest, but v1 doesn't wire that. ✅

---

## Nits

### 1. Section 1 docstring mentions "fabrication" but `GroundTruthResult` has no `fabricated` field

Cosmetic. The class is named `GroundTruthVerifier`, the result has `verified: bool` + `score: float`. The "fabrication-detection" framing is in the prompt body but not in the dataclass field names. Acceptable; flagging for future polish.

### 2. Footer line drift on `runtime.emit_event`

Footer says `runtime.py:775`; actual is 785. Off by 10. Update.

### 3. `_emit()` swallows exception silently — consistent with three-tier pattern

```python
except Exception:
    logger.warning(
        "AD-528: %s emit failed (booking_id=%s, agent_id=%s)",
        et.value, result.booking_id, result.agent_id, exc_info=True,
    )
```

Tier-2 log-and-degrade. ✅ Correct for diagnostics.

### 4. `episode.completed_at` field overlap with Episode.timestamp

`GroundTruthResult.completed_at` is the moment the verified action completed; `Episode.timestamp` is the moment the episode was stored. These are distinct concepts. Required #1's fix should preserve both via `dag_summary`.

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ✅ Applied

`runtime.ground_truth_verifier` and `runtime.verification_episode_writer` — both public.

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

No new pyproject deps. v1 reads existing surfaces only.

### Coordinator-then-dispatch (Wave-5 convention #3) — ✅ Applied

v1 observation-only; active rejection deferred to AD-528b. ✅

### Superset-filter discipline (Wave-5 convention #4) — ✅ Applied

`GroundTruthVerifier` reads existing surfaces (BookingJournal, event_log) without intercepting. No existing flow is gated. ✅

### `init_<phase>` startup signatures (Wave-5 convention #5) — ✅ Applied

Section 5 wires from `startup/finalize.py` (receives `runtime` directly). ✅

### Verify-first for anchors (Wave-5 convention #6) — ⚠️ Required #1 + #3

The footer claims `episode = {...}; await store(episode)` works, which is the phantom-API issue Required #1 catches. The footer should have included:

```
grep -n "class Episode\|async def store" src/probos/cognitive/episodic.py src/probos/types.py
```

That grep would have shown the typed signature.

### No-theater discipline (Wave-5 convention #7) — ✅ Applied (after Required #1 fix)

After Required #1 resolves, both `GroundTruthVerifier` and `VerificationEpisodeWriter` do real work today (read journals, query event log, write real Episode). No deferred-to-v2 stubs.

### TYPE_CHECKING cross-layer imports (Wave-6 note) — ⚠️ Required #2

The pattern is correctly applied in Section 1, but the Builder needs the ALLOWED_EXCEPTIONS entry call-out — Required #2.

### ASCII-only source comments (Wave-6 note) — ✅ Applied

Verified.

### Anchor-chain fallback (Wave-6 note) — ✅ Applied

Section 4 anchor chain terminates at `orders: OrdersConfig` (config.py:1593). ✅

### Section 0 EventTypes — ✅ Clean

`VERIFICATION_PASSED`, `VERIFICATION_FAILED` — verified absent. No collision with other Wave 7 prompts.

### Episode storage non-optional for v1 — ✅ Documented

```
grep -n "write_episode" prompts/ad-528-ground-truth-task-verification.md | head -3
```

`GroundTruthConfig.write_episode: bool = True` (Section 4). Acceptance criteria explicitly states episode storage is integrated. ✅

### Independence from AD-451 — ✅ Documented

"What This Does NOT Change" explicitly says AD-451 ReconciliationEscalator is NOT integrated. Future seam (AD-528b emits VerificationResult that ReconciliationEscalator could consume) noted. ✅

### `BookingJournal` and `Workforce.get_booking_journal` — ✅ Verified

```
grep -n "class BookingJournal\|async def get_booking_journal" src/probos/workforce.py
  738: class BookingJournal:
  1514: async def get_booking_journal(self, booking_id: str) -> list[BookingJournal]:
```

AD-528's reads are valid. ✅

### `event_log.query` signature — ✅ Verified

```python
events = await log.query(agent_id=agent_id, limit=200)
```

Verified — `query(category=None, agent_id=None, limit=100)` accepts `agent_id` kwarg. AD-528 uses it correctly. ✅

### AD-592 confabulation guard orthogonality — ✅ Documented

AD-592 is the LLM prompt surface; AD-528 is the runtime verification surface. "What This Does NOT Change" explicitly addresses this. ✅

### Test plan — ⚠️ 14 tests but Test 12 will fail under Required #1's current spec

Test #12 (`test_episode_writer_stores_episode`) currently asserts the dict is passed to `store(...)`. After Required #1's fix, the test asserts an `Episode` instance is passed. Update the test description.

---

## Verdict Summary

**Three blocking issues:**
1. `EpisodicMemory.store()` requires `Episode` dataclass; AD-528 passes raw dict. Mechanical fix in Section 2.
2. ALLOWED_EXCEPTIONS entry for `cognitive/ground_truth.py → probos.workforce` cross-layer import.
3. `MemorySource` enum value verification — Builder must grep for valid values; recommend `"direct"` for v1.

**5 Recommended findings:** docstring clarity, window tightening note, threshold boundary doc, truncation rationale, AD-451 orthogonality (already addressed).

**4 Nits:** cosmetic.

**Wave-5/6 conventions:** all applied except convention #6 (verify-first) which slipped on the Episode dataclass type — Required #1.

**Build-readiness after fix:** ~15 minutes architect time. Required #1 + #2 are concrete edits. Required #3 is a Builder grep step.

**Recommended build order:** AD-528 third in Wave 7 (after AD-466 and AD-456). No cross-AD dependencies; reads existing surfaces only.

---

## Second-Pass Review (2026-05-01)

**Verdict:** ✅ **Approved** — all 3 Required findings resolved; Episode dataclass usage matches `types.py:411` field-by-field; ALLOWED_EXCEPTIONS Section 6 documented.

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R#1: EpisodicMemory.store(dict) phantom | ✅ Resolved | Section 2 line 277 imports `Episode`, `MemorySource` from `probos.types`; constructs typed `Episode(timestamp=, user_input=, agent_ids=, dag_summary={...}, source=MemorySource.DIRECT.value, importance=7\|4, correlation_id="")`. All field names verified against `types.py:411-435`. Dict approach removed. |
| R#2: ALLOWED_EXCEPTIONS entry | ✅ Resolved | New Section 6 (lines 402-426) explicitly instructs Builder to add `("cognitive/ground_truth.py", "probos.workforce")` to `tests/test_layer_boundaries.py` ALLOWED_EXCEPTIONS with full SEARCH/REPLACE block and justification comment. Mirrors AD-451 / BF-085 precedent. |
| R#3: MemorySource enum value | ✅ Resolved | `MemorySource.DIRECT.value` ("direct") used; verified at `types.py:344`. Builder note documents the AD-541 semantic alignment. |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1: _fetch_journal fallback doc | ✅ Applied | Docstring updated. |
| rec#2: window tightening note | ✅ Applied | Documented in "What This Does NOT Change". |
| rec#3: threshold boundary semantics | ✅ Applied | Test #10 description clarified: "boundary is inclusive; >= comparison." |
| rec#4: claimed_summary truncation rationale | ✅ Applied | Section 2 docstring documents 1000-char truncation rationale. |
| rec#5: AD-451 orthogonality | ✅ Already addressed | Pass-1 prompt body already correct; preserved in revision. |

| Pass-1 Nits | Status | Notes |
|---|---|---|
| nit#1: confabulation framing | 📦 Deferred | Cosmetic; AD-528b polish. |
| nit#2: footer line drift | ✅ Applied | `runtime.emit_event` line corrected to 785. |
| nit#3: _emit() exception swallow | ✅ Preserved | Tier-2 log-and-degrade. |
| nit#4: completed_at vs timestamp distinction | ✅ Applied | `dag_summary["completed_at"]` (verifier moment) + `Episode.timestamp` (storage moment) both populated. |

### New Findings (introduced during revision)

None.

### Verified Against Revised Codebase Claims

- `Episode` dataclass at `types.py:411` — confirmed all field names match revision usage:
  - `timestamp: float = 0.0` ✅
  - `user_input: str = ""` ✅
  - `agent_ids: list[str]` ✅
  - `dag_summary: dict[str, Any]` ✅
  - `source: str = "direct"` (default value) ✅ — matches `MemorySource.DIRECT.value`
  - `importance: int = 5` (default; revision uses 7|4) ✅
  - `correlation_id: str = ""` ✅
- `MemorySource.DIRECT = "direct"` at `types.py:344` — confirmed.
- `EpisodicMemory.store(episode: Episode)` at `cognitive/episodic.py:942` — confirmed signature.
- `tests/test_layer_boundaries.py` ALLOWED_EXCEPTIONS at line 53 — confirmed.
- AD-451's `validation_framework.py → agents.red_team` exception entry verified post-Wave 6 commit `4ed9ab2`.
- `dag_summary` structure (dict with verification metadata under "kind", "booking_id", "verified", "score", "signals", "completed_at") is consistent with how other ADs use the field for typed payloads.
- `importance=7 if not result.verified else 4` — failed verifications biased toward retention per AD-598 importance scoring (default 5 = neutral; 7 = above-neutral retention; 4 = below-neutral).

### Cross-Cutting Convention Audit

| Cross-cutting fix | Applied? | Evidence |
|---|---|---|
| Phantom-API fix: AD-528 Episode | ✅ Applied | Episode constructed correctly with verified field names. |
| AD-528 ALLOWED_EXCEPTIONS section | ✅ Applied | Section 6 documents the addition. |

### Verdict

**✅ Approved.** Build-ready as AD-528 third in Wave 7. Mechanical fixes applied cleanly; no scope expansion needed.
