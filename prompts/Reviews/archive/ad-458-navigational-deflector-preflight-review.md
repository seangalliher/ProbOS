# Review: AD-458 — Navigational Deflector (Pre-Flight Validation)

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ❌ **Not Ready** — two phantom APIs (`BuildResult(success=False, error=...)` will TypeError; `client.operational_status.deep` does not exist) cause Section 4 to crash and Section 2's `LLMTierReachableCheck` to be permanent theater. Both fixes are mechanical but Required.

Pre-flagged drafting decision (BuildResult signature) was the right concern — verification confirms the issue.

---

## Required (must fix before building)

### 1. `BuildResult(success=False, error=...)` will TypeError — `spec` is required

Section 4 SEARCH/REPLACE:

```python
return BuildResult(
    success=False,
    error="pre-flight validation failed: ...",
)
```

Verified — `BuildResult` requires `spec` as the second non-default field:

```
view src/probos/cognitive/builder.py:160-176

@dataclass
class BuildResult:
    """Result of a builder agent execution."""

    success: bool
    spec: BuildSpec
    files_written: list[str] = field(default_factory=list)
    ...
    error: str = ""
    ...
```

`success` and `spec` are non-default; everything else has defaults. Python dataclass field-ordering rules mean `BuildResult(success=False, error="...")` raises `TypeError: __init__() missing 1 required positional argument: 'spec'`.

The existing pattern in `execute_approved_build()` is "create-then-mutate":

```
view src/probos/cognitive/builder.py:2504-2515
  result = BuildResult(success=False, spec=spec)
  ...
  if await _is_dirty_working_tree(work_dir):
      result.error = "Working tree has uncommitted changes. ..."
      return result
```

**Action:** Rewrite Section 4 to match the existing pattern:

```python
    # AD-458: Pre-flight validation
    pre_flight = getattr(runtime, "pre_flight_runner", None) if runtime else None
    if pre_flight is not None:
        report = await pre_flight.run(spec, emit_event=runtime.emit_event)
        if not report.passed:
            result = BuildResult(success=False, spec=spec)
            result.error = "pre-flight validation failed: " + ", ".join(
                r.detail for r in report.results if not r.passed and r.blocking
            )
            return result
```

Note also — `runtime` is `ProbOSRuntime | None = None` per the function signature (verified at builder.py:2491). Need the `if runtime else None` guard, otherwise the `getattr` runs on `None` and the prompt's bare `getattr(runtime, ...)` is fine (None passes through `getattr` cleanly). But the subsequent `runtime.emit_event` would crash on `None` — needs an explicit None check.

### 2. `client.operational_status.deep` is a phantom API

`LLMTierReachableCheck` (Section 2, line 195-223):

```python
status = getattr(client, "operational_status", None)
...
deep = getattr(status, "deep", "operational")
ok = str(deep).lower() == "operational"
```

Verified — `operational_status` does not exist:

```
grep -rn "operational_status" src/probos/
  (no matches)
```

The actual probe surface is `_tier_status` (private dict) and `start_health_probe()` (BF-246):

```
grep -n "_tier_status\|start_health_probe\|_health_probe" src/probos/cognitive/llm_client.py
  100:    self._tier_status: dict[str, bool] = {}
  141:    # BF-246: Periodic health probe for recovery from extended outages
  263:    self._tier_status[tier] = results[tier]
  273: async def start_health_probe(
  279: """BF-246: Periodic connectivity probe for recovery from extended outages."""
```

The check, as written, will:
1. `getattr(client, "operational_status", None)` returns `None`.
2. The defensive branch returns `passed=True` with `"no operational_status — assuming reachable"`.
3. The check is permanent theater — never actually probes.

This is the AD-455 v1 theater anti-pattern from Wave 5 retrospective convention #3 — "deliver the coordinator first, defer the dispatch mechanism" applies here. AD-458 wants real pre-flight; theater that always passes is worse than not having the check.

**Action:** Pick one:

- **(a)** AD-458 introduces a public `is_tier_operational(tier_name: str) -> bool` accessor on `TieredLLMClient` as a Section 2.5. Reads `self._tier_status.get(tier_name, True)` (default True so unprobed tiers don't block builds).

- **(b)** Remove `LLMTierReachableCheck` from v1 entirely. Defer to AD-458b. v1 ships with three checks: target-files-exist, target-files-writable, token-budget-soft.

- **(c)** AD-458's check makes a real HEAD probe to the deep-tier URL. Substantial scope expansion (network I/O, timeout handling, retry policy) — surfaces to a separate AD.

Recommended **(a)** — small public accessor, real signal, no scope creep.

### 3. `Path(__file__).resolve().parents[3]` repo-root claim — verify the parent depth

Section 6 finalize.py wiring:

```python
repo_root = Path(__file__).resolve().parents[3]
```

The file is `src/probos/startup/finalize.py`. Counting parents:
- `parents[0]` = `src/probos/startup/`
- `parents[1]` = `src/probos/`
- `parents[2]` = `src/`
- `parents[3]` = repo root

Confirmed — `parents[3]` is correct. ✅ But the prompt comment says "file → startup → probos → src → REPO_ROOT (3 parents)" which is misleading (it's 4 transitions, indexed 0-3). Clarify: `parents[3]` is the 4th index, equivalent to `.parent.parent.parent.parent`.

This is technically correct but the explanation is muddled. Fix the verify-first comment text in Section 6.

### 4. Section 4 inserts middleware AFTER branch creation; intent is BEFORE expensive ops

The prompt says "Insert at the top of the function body" but the function body has dirty-tree check (line 2510) and branch creation (line 2524) BEFORE any LLM/file work. The AD's value is "validate before expensive ops" — branch creation is a cheap git operation, not expensive.

Current ordering as written would be:
1. Save current branch (cheap)
2. Verify clean tree (cheap)
3. Generate branch name (cheap)
4. Create branch (cheap)
5. **PRE-FLIGHT** ← prompt says "top of function body"

The prompt's "top of function body" is ambiguous. Recommended insertion: AFTER the dirty-tree check and BEFORE branch creation (between line 2515 and line 2517). This way:
- Pre-flight runs after we know the tree is clean
- Pre-flight runs before we create a branch we'd then have to delete
- Pre-flight failure leaves the working tree untouched

If pre-flight runs at the very top (line 2504), a pre-flight failure would still leave a clean state (no branch created, no files written). But the existing pattern is "save branch → check clean → generate branch → create branch", and inserting between steps 2 and 3 keeps the failure isolation cleanest.

**Action:** Be explicit about insertion point. Recommend after `_is_dirty_working_tree` check (after line 2515), before branch generation (before line 2517).

---

## Recommended

### 1. `TokenBudgetCheck` is theater (non-blocking, no real check)

Section 2's `TokenBudgetCheck` returns `passed=True, blocking=False` unconditionally. The docstring says "AD-617b layer enforces; AD-458 is heads-up". But heads-up about what? The check never reads token state.

If the v1 contract is "token budget enforcement is at AD-617b", remove `TokenBudgetCheck` from v1 and document it as deferred to AD-458b. A check that always passes adds no signal.

If the intent is "warn when remaining budget is low", read `runtime.cognitive_journal.remaining_tokens()` (or whatever the real surface is) and emit a non-blocking failure when below threshold.

### 2. `TargetFilesWritableCheck` — `os.access` returns wrong answer on Windows for read-only dirs

`os.access(p, os.W_OK)` on Windows can return `True` for files inside a read-only directory or for files protected by ACLs. The check is approximate.

For v1, this is acceptable — the prompt's "What This Does NOT Change" should call out the Windows ACL limitation. Operator running on Windows + custom ACLs may see false-positive pre-flight passes.

### 3. `PreFlightRunner.checks` is a `list` not a `tuple` — mutability concern

```python
@dataclass
class PreFlightRunner:
    checks: list[PreFlightCheck] = field(default_factory=list)
```

A consumer could mutate `runner.checks` after construction. For a coordinator that's stateless-per-run, immutability would be safer:

```python
@dataclass(frozen=True)
class PreFlightRunner:
    checks: tuple[PreFlightCheck, ...] = ()
```

Forces construction-time wiring. Minor — list-vs-tuple is a style call.

### 4. EventType `PREFLIGHT_FAILED` payload — include the `report.passed` aggregate

The emit currently sends `failures` list only. The aggregate `passed=False` is implied by the event firing, but downstream consumers (HXI, ops dashboards) may want the full report. Add `"started_at"`, `"completed_at"`, `"check_count"` to the payload for trace-completeness.

---

## Nits

### 1. Section 5 SEARCH anchor depends on AD-457

Section 5 anchors on `engineering: EngineeringConfig = EngineeringConfig()  # AD-457`. Builder note correctly identifies the fallback (`validation_framework: ValidationFrameworkConfig`). ✅ Anchor chain handled.

### 2. `import os` inside `TargetFilesWritableCheck.check()` — move to module-level

```python
async def check(self, spec: "BuildSpec") -> PreFlightResult:
    ...
    try:
        import os
        if not os.access(p, os.W_OK):
```

Local import inside a method runs on every call. Move to module-level imports at top of file.

### 3. Test 11 `test_pre_flight_runner_continues_on_non_blocking_failure` — verify behavior

The runner short-circuits on first BLOCKING failure but continues past non-blocking failures. The test name is correct but the implementation needs to confirm: a non-blocking failure followed by a passing blocking check should report `passed=True` (no blocking failures occurred). Test description should clarify the assertion.

### 4. Acceptance criterion "TokenBudgetCheck is non-blocking (soft)" reflects theater, not real check

If Required #2's recommended fix removes `TokenBudgetCheck` entirely, drop this line.

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ✅ Applied

```
runtime.pre_flight_runner = PreFlightRunner(...)  # Section 6, finalize.py
```

No leading underscore. Public. Verified compliant.

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

No new pyproject deps. Uses `pathlib`, `os`, `time`, `dataclasses`, `typing.Protocol` — all stdlib. ✅

### Coordinator-then-dispatch (Wave-5 convention #3) — ⚠️ Partial

The `SelfVerificationHook` in AD-451 follows the pattern. But AD-458's `TokenBudgetCheck` and `LLMTierReachableCheck` ship as theater (Required #2 covers the LLM check; Recommended #1 covers token check). v1 should ship only the checks with real signal — the others belong in AD-458b.

### Superset-filter discipline (Wave-5 convention #4) — ⚠️ Partial

`TokenBudgetCheck` is documented as "soft" (non-blocking) so it does NOT intercept cases AD-617b already covers. ✅ Filter discipline is correct.

But: `LLMTierReachableCheck` could intercept builds during transient LLM outages — a case the existing test infrastructure doesn't have a contract for. If the deep tier is briefly degraded but recovers within the LLM client's retry window, AD-458 would block builds where the existing flow would have succeeded. Tighten the threshold to "deep tier has been DOWN for >N seconds", not "deep tier is currently DEGRADED".

### `init_<phase>` startup signatures (Wave-5 convention #5) — ✅ Applied

`startup/finalize.py` receives `runtime` directly. Verified.

### Verify-first for anchors (Wave-5 convention #6) — ⚠️ Two phantom APIs found

- `BuildResult(success=False, error=...)` — Required #1.
- `client.operational_status.deep` — Required #2.
- Both flagged in dispatch's pre-flagged drafting decision; verification confirmed both as real issues.

### Section 0 EventType — ✅ Clean

`PREFLIGHT_FAILED = "preflight_failed"` — verified absent in `events.py`.

### `BuildSpec` and `BuilderAgent` — ✅ Verified

```
grep -n "^class BuildSpec\|^class BuilderAgent\|^async def execute_approved_build" src/probos/cognitive/builder.py
  146: class BuildSpec:
  160: class BuildResult:
  1690: class BuilderAgent(CognitiveAgent):
  2482: async def execute_approved_build(
```

Prompt's claims are accurate.

### `BuildSpec.target_files`, `BuildSpec.title` — needs verification

Section 1's `TargetFilesExistCheck` reads `spec.target_files`. The prompt does not paste grep evidence for `BuildSpec.target_files` and `BuildSpec.title`. Should be in the footer:

```
grep -n "target_files\|title:" src/probos/cognitive/builder.py | head -5
```

Likely fine (BuildSpec is a substantial dataclass), but the verify-first standing order requires it.

### Test plan — ⚠️ 12 tests but 1 covers theater

Tests 1-3, 5-12 are real. Test 8 (`test_llm_tier_reachable_check_operational`) and Test 9 (`test_llm_tier_reachable_check_degraded`) test the phantom `operational_status.deep` API — they pass because the test's fake `operational_status` is a stub, but they don't reflect production behavior. After Required #2 fix, these tests should be rewritten against the real surface.

### `runtime.llm_client` access — ✅ Verified

`runtime.llm_client` exists (line 347).

### `bridge_alerts.AlertSeverity` orthogonality — ✅ Verified

`bridge_alerts.py:24 AlertSeverity` is severity-based (info/warning/critical), distinct from AD-458 pre-flight. No overlap.

---

## Verdict Summary

**Two blocking issues:**
1. Section 4 `BuildResult(success=False, error=...)` will TypeError. Trivial fix.
2. Section 2 `LLMTierReachableCheck` reads phantom `operational_status` — permanent theater. Pick one of three resolutions; recommend (a) add public accessor.

**Four Recommended findings:** insertion point clarification, theater removal, immutability, payload completeness.

**Four Nits:** cosmetic + test description.

**Wave-5 conventions:** 4 of 6 fully applied. Convention #3 (coordinator-then-dispatch) and convention #4 (superset filter) have partial adherence — Required #2 fix would bring them to full.

**Build-readiness after fix:** ~15 minutes architect time. Re-review of Section 2, Section 4, and Section 6 verify-first comment.

---

## Second-Pass Review (2026-05-01)

**Verdict:** ✅ **Approved** — phantom APIs eliminated; v1 scope reduced cleanly to two real checks; create-then-mutate pattern matches live `BuildResult`. v1 is buildable with substantive content (not gutted by the AD-458b deferral).

### Resolution Audit

| Pass-1 Required | Status | Evidence in revised prompt |
|---|---|---|
| R#1: `BuildResult(success=False, error=...)` TypeError | ✅ Resolved | Section 4 SEARCH/REPLACE at lines 296-321 inserts after the existing `result.error = ...; return result` pattern (`builder.py:2509-2515` verified). New code reuses the pre-existing `result` variable from line 2504; mutates `result.error` and returns. No phantom direct-construct form remains in any SEARCH/REPLACE block. |
| R#2: phantom `client.operational_status.deep` | ✅ Resolved | `LLMTierReachableCheck` deferred wholesale to AD-458b. Class definition removed from Section 2; finalize.py wiring removed; Section 1 imports updated. Module-level deferral comment at lines 198-203 documents the AD-458b plan. The only `operational_status` references remaining are in the verify-first comment (line 323) and Revision section (line 516) — both document what was wrong, not what is shipped. ✅ |
| R#3: `Path.parents[3]` explanation cleanup | ✅ Resolved | Section 6 lines 401-407 show the parent-level mapping inline (`parents[0] = src/probos/startup/`, `parents[1] = src/probos/`, `parents[2] = src/`, `parents[3] = repo root`). No more "3 parents" mistake. |
| R#4: insertion point clarification | ✅ Resolved | Section 4 SEARCH block anchors on `# 1a. Verify clean working tree` (lines 285-294); REPLACE inserts pre-flight at "# 1b" comment (lines 306-318) — between dirty-tree check and branch generation. Failure isolation explicit. |

| Pass-1 Recommended | Status | Notes |
|---|---|---|
| rec#1 (`TokenBudgetCheck` is theater) | ✅ Applied | Deferred wholesale to AD-458b. Same rationale as LLMTier. |
| rec#2 (Windows ACL limitation) | ✅ Applied | "What This Does NOT Change" line 433 documents `os.access` ACL approximation. |
| rec#3 (`PreFlightRunner.checks` immutability) | 📦 Deferred | Kept as `list` per Revision rationale — frozen-tuple form would break `field(default_factory=list)` pattern. Acceptable. |
| rec#4 (PREFLIGHT_FAILED payload completeness) | ✅ Applied | `started_at`, `completed_at`, `check_count` added to emit payload (Section 3 line 305-308 region). |

| Pass-1 Nits | Status | Notes |
|---|---|---|
| nit#1 (Section 5 anchor chain) | ✅ Applied (cross-cutting #3) | Section 5 anchor chain extended to AD-440 terminal. |
| nit#2 (`import os` to module-level) | ✅ Applied | Section 1 line 65 `import os` at module top. |
| nit#3 (Test 8 description) | ✅ Applied | Test 8 description in revised plan: "non-blocking failure recorded but does not abort the run; report.passed reflects only blocking failures". |
| nit#4 (TokenBudgetCheck acceptance criterion) | ✅ Applied | Acceptance criterion line dropped from list. |

### New Findings (introduced during revision)

1. **Minor: `PreFlightCheck` Protocol decoration uses unconventional `runtime_checkable(PreFlightCheck)` post-assignment instead of the standard decorator form.** Section 1 lines 119-121:

   ```python
   PreFlightCheck = runtime_checkable(PreFlightCheck)  # type: ignore[misc]
   ```

   The standard form is `@runtime_checkable` above the class definition. The post-assignment with `# type: ignore[misc]` works but is non-standard. Test #10 (`test_pre_flight_check_protocol_is_runtime_checkable`) would still pass.

   **Severity:** Nit. Both forms are functionally equivalent. The type:ignore comment hints at type-checker issues; the standard decorator form is cleaner. Builder may prefer the standard form during implementation; flagging here so the second-pass reviewer doesn't miss it.

   **Resolution:** Builder discretion. Either form is acceptable.

### Verified Against Revised Codebase Claims

- `BuildResult` requires `spec` as 2nd non-default field at `cognitive/builder.py:160-176` — confirmed via direct read; matches the prompt's assertion.
- `result = BuildResult(success=False, spec=spec)` precedent at `builder.py:2504` — confirmed; the prompt's create-then-mutate pattern is verbatim from live code.
- `_is_dirty_working_tree` and `# 2. Generate branch name` SEARCH anchor at `builder.py:2509-2517` — confirmed via direct read; SEARCH anchor matches verbatim.
- `_tier_status` private at `cognitive/llm_client.py:100` — confirmed; defer to AD-458b is justified.
- `orders: OrdersConfig` at `config.py:1593` — confirmed terminal anchor.

### Cross-Cutting Convention Audit

| Cross-cutting fix | Applied? | Evidence |
|---|---|---|
| #1 No-theater discipline | ✅ Applied wholesale | LLMTierReachableCheck + TokenBudgetCheck deferred to AD-458b (no v1 stubs). v1 ships TWO real-work checks: TargetFilesExistCheck (filesystem read) + TargetFilesWritableCheck (filesystem read + ACL). |
| #2 Verify-first defensive-read | ✅ Applied | `_tier_status` private nature documented in Solution Overview; deferral to AD-458b carries forward the public-accessor design. No phantom defensive reads remaining. |
| #3 Anchor-chain fallback | ✅ Applied | Section 5 chain: `engineering` (AD-457) → `validation_framework` (AD-451) → `orders: OrdersConfig` (AD-440) terminal. |
| #6 BuildResult field-name fix | ✅ Applied | Section 4 SEARCH/REPLACE uses `result.error = ...; return result` matching `builder.py:2511-2515`. |

### v1 Scope Audit (Hard-Stop Check)

The dispatch's hard-stop: "If AD-458 v1 is now too thin to be buildable (gutted by the deferral to AD-458b), surface."

**Not triggered.** AD-458 v1 still ships:
- `PreFlightCheck` Protocol (decorated `@runtime_checkable`)
- `PreFlightResult` and `PreFlightReport` dataclasses
- `TargetFilesExistCheck` — real filesystem check
- `TargetFilesWritableCheck` — real filesystem + ACL check
- `PreFlightRunner` — composes checks, short-circuits on blocking failure, emits `PREFLIGHT_FAILED`
- Builder integration in `execute_approved_build()` (failure isolation between dirty-tree check and branch creation)
- 10 tests, full config + finalize wiring + REST router not needed (no UI panel)

This is substantive — file-existence and writability ARE real value adds for catching read-only build targets, missing dependency files, and Windows ACL issues before LLM calls fire. AD-458b will add the LLM-tier and token-budget checks once their public-accessor surfaces exist.

### Verdict

**✅ Approved.** Build-ready. The minor `runtime_checkable` decorator-vs-postassignment style choice is Builder discretion, not a blocker.

