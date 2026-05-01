# AD-458: Navigational Deflector — Pre-Flight Validation

**Status:** Ready for builder
**Dependencies:** Builds on existing `BuilderAgent` and `BuildSpec` (verified at `src/probos/cognitive/builder.py:146,1690`) and `execute_approved_build` (`builder.py:2482`). Mirrors the AD-446 `CompensationHandler` middleware pattern (separate handler invoked by the existing pipeline, not a re-architecture).
**Estimated tests:** ~12
**Risk:** Medium — extends the build pipeline. No new agent pool. No consensus paths.

---

## Problem

`BuilderAgent.act()` (verified at `src/probos/cognitive/builder.py:2176`) and the package-level `execute_approved_build()` (`builder.py:2482`) start expensive operations (LLM calls, file writes, test runs) without a structured pre-flight validation step. If the target file is read-only, the LLM proxy is unreachable, or token budget is insufficient, the failure surfaces deep in the build flow and wastes work.

`grep -n "pre_flight\|preflight" src/probos/cognitive/builder.py` returns no matches — no pre-flight surface exists today.

What is needed:

1. **`PreFlightCheck`** — a small protocol: `async def check(spec) -> PreFlightResult`. Each check is independent.
2. **`PreFlightRunner`** — runs a list of checks, fails fast on first failure, returns a `PreFlightResult` aggregate.
3. **Builder integration** — call the runner before `execute_approved_build` does its first LLM call. Failure emits `EventType.PREFLIGHT_FAILED` and aborts the build cleanly.

## Solution Overview

Create `src/probos/cognitive/pre_flight.py` (new). Two layers:

- **Protocol layer** — `PreFlightCheck` Protocol + `PreFlightResult` dataclass + two built-in checks (target-files-exist, target-files-writable).
- **Runner layer** — `PreFlightRunner` composes the checks. Stateless. Each `run(spec)` call is independent.

This is **middleware between approval and execution.** AD-458 does NOT change `BuilderAgent.act()` itself, does NOT change `BuildSpec` schema, does NOT add new LLM calls. The runner is invoked from `execute_approved_build()` after the existing dirty-tree check, before branch creation.

The AD-446 `CompensationHandler` (already in the codebase) is the architectural model: a small handler invoked by the existing pipeline, not a re-architecture.

**v1 scope (no-theater discipline per Wave 5 retrospective convention #3):**

v1 ships only the two checks that do real work today: `TargetFilesExistCheck` (reads filesystem) and `TargetFilesWritableCheck` (reads filesystem + ACLs). Both have concrete signal even with zero runtime infrastructure. Two checks deferred to **AD-458b**:

- `LLMTierReachableCheck` — needs a public LLM-tier health accessor that doesn't exist today (`_tier_status` is private at `cognitive/llm_client.py:100`). AD-458b will introduce the public `is_tier_operational(tier_name) -> bool` accessor and add the check.
- `TokenBudgetCheck` — token budget enforcement already lives in AD-617b (proactive cognitive loop). A separate pre-flight soft check would either duplicate enforcement or ship as theater. AD-458b will evaluate whether a heads-up signal is needed once AD-617b's surface is exercised.

---

## Section 0: Event Types

Add to `src/probos/events.py`:

```
PREFLIGHT_FAILED = "preflight_failed"  # AD-458
```

One new value. Verified absent via `grep -n "PREFLIGHT" src/probos/events.py` (no matches).

---

## Section 1: `PreFlightCheck` Protocol + `PreFlightResult`

**File:** `src/probos/cognitive/pre_flight.py` (new)

```python
"""AD-458: Navigational Deflector — Pre-Flight Validation.

Middleware between build approval and execution. Validates that the
build path is clear before the BuilderAgent commits expensive resources
(LLM calls, file writes). Mirrors the AD-446 CompensationHandler shape:
a small handler invoked by the existing pipeline, not a re-architecture.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from probos.events import EventType

if TYPE_CHECKING:
    from probos.cognitive.builder import BuildSpec

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PreFlightResult:
    """Result of a single pre-flight check, or the aggregate."""

    passed: bool
    check_name: str
    detail: str = ""
    blocking: bool = True


@dataclass(frozen=True)
class PreFlightReport:
    """Aggregate result of running all checks for one build."""

    passed: bool
    results: list[PreFlightResult]
    started_at: float
    completed_at: float


class PreFlightCheck(Protocol):
    """Protocol for a single pre-flight check.

    Implementations must be async (some checks need I/O — file stat). They
    must NOT mutate any state. Decorated `@runtime_checkable` so tests can
    assert via `isinstance(impl, PreFlightCheck)`.
    """

    name: str

    async def check(self, spec: "BuildSpec") -> PreFlightResult:
        ...


# Apply the runtime_checkable decorator separately so the Protocol body stays
# compatible with PEP 544 + dataclass tooling.
PreFlightCheck = runtime_checkable(PreFlightCheck)  # type: ignore[misc]
```

---

## Section 2: Built-in checks

**File:** `src/probos/cognitive/pre_flight.py` (continued)

```python
class TargetFilesExistCheck:
    """Verify target files in BuildSpec exist (for MODIFY mode)."""

    name = "target_files_exist"

    def __init__(self, *, repo_root: Path) -> None:
        self._repo_root = repo_root

    async def check(self, spec: "BuildSpec") -> PreFlightResult:
        target_files: list[str] = list(getattr(spec, "target_files", []) or [])
        if not target_files:
            return PreFlightResult(
                passed=True, check_name=self.name,
                detail="no target_files (CREATE mode)",
            )
        missing = [
            t for t in target_files
            if not (self._repo_root / t).exists()
        ]
        if missing:
            return PreFlightResult(
                passed=False, check_name=self.name,
                detail=f"missing: {', '.join(missing[:5])}",
            )
        return PreFlightResult(
            passed=True, check_name=self.name,
            detail=f"{len(target_files)} target file(s) verified",
        )


class TargetFilesWritableCheck:
    """Verify target files in BuildSpec are writable."""

    name = "target_files_writable"

    def __init__(self, *, repo_root: Path) -> None:
        self._repo_root = repo_root

    async def check(self, spec: "BuildSpec") -> PreFlightResult:
        target_files: list[str] = list(getattr(spec, "target_files", []) or [])
        if not target_files:
            return PreFlightResult(
                passed=True, check_name=self.name,
                detail="no target_files",
            )
        unwritable: list[str] = []
        for t in target_files:
            p = self._repo_root / t
            if not p.exists():
                continue
            try:
                if not os.access(p, os.W_OK):
                    unwritable.append(t)
            except Exception:
                unwritable.append(t)
        if unwritable:
            return PreFlightResult(
                passed=False, check_name=self.name,
                detail=f"unwritable: {', '.join(unwritable[:5])}",
            )
        return PreFlightResult(
            passed=True, check_name=self.name,
            detail=f"{len(target_files)} target file(s) writable",
        )


# AD-458b deferred:
#   - LLMTierReachableCheck: needs public is_tier_operational(...) accessor on
#     TieredLLMClient (today's _tier_status is private at llm_client.py:100).
#   - TokenBudgetCheck: hard enforcement already lives in AD-617b proactive
#     cognitive loop; a soft pre-flight gate would either duplicate or ship
#     as theater. Defer until AD-617b surface is exercised.
```

> Builder note: `import os` is added to the module-level imports at the top of `pre_flight.py` (not inside the method body) per ProbOS convention.

---

## Section 3: `PreFlightRunner`

**File:** `src/probos/cognitive/pre_flight.py` (continued)

```python
@dataclass
class PreFlightRunner:
    """Composes a list of PreFlightCheck instances.

    `run(spec)` calls each check in order. First blocking failure short-circuits
    the run. Non-blocking failures are recorded but do not abort.

    Stateless on construction. Each run produces a fresh PreFlightReport.
    """

    checks: list[PreFlightCheck] = field(default_factory=list)

    async def run(self, spec: "BuildSpec", *, emit_event: Any | None = None) -> PreFlightReport:
        started = time.time()
        results: list[PreFlightResult] = []
        for check in self.checks:
            try:
                r = await check.check(spec)
            except Exception as exc:
                logger.warning(
                    "AD-458: check '%s' raised; treating as non-blocking failure",
                    check.name, exc_info=True,
                )
                r = PreFlightResult(
                    passed=False, check_name=check.name,
                    detail=f"check raised: {exc}", blocking=False,
                )
            results.append(r)
            if not r.passed and r.blocking:
                break
        passed = all(r.passed for r in results if r.blocking)
        completed = time.time()
        report = PreFlightReport(
            passed=passed,
            results=results,
            started_at=started,
            completed_at=completed,
        )
        if not passed and emit_event is not None:
            try:
                emit_event(
                    EventType.PREFLIGHT_FAILED,
                    {
                        "build_title": getattr(spec, "title", ""),
                        "started_at": started,
                        "completed_at": completed,
                        "check_count": len(results),
                        "failures": [
                            {"check": r.check_name, "detail": r.detail}
                            for r in results
                            if not r.passed and r.blocking
                        ],
                    },
                )
            except Exception:
                logger.warning("AD-458: PREFLIGHT_FAILED emit failed", exc_info=True)
        return report
```

---

## Section 4: Builder integration

**File:** `src/probos/cognitive/builder.py`

Find `execute_approved_build()` (verified at `builder.py:2482`). The function signature receives `runtime: ProbOSRuntime | None = None` (verified at `builder.py:2491`). Insert pre-flight invocation **after the dirty-tree check (line 2515) and BEFORE branch creation (line 2517)** — failure isolation: if pre-flight fails, no branch is created, no files written, working tree untouched.

Match the existing `BuildResult` create-then-mutate pattern (verified at `builder.py:2504`: `result = BuildResult(success=False, spec=spec)`; the dataclass requires `spec` as a non-default field per `builder.py:160-176`).

SEARCH:
```python
    # 1a. Verify clean working tree (prevent contaminating build branch)
    if await _is_dirty_working_tree(work_dir):
        result.error = (
            "Working tree has uncommitted changes. "
            "Commit or stash changes before running a build."
        )
        return result

    # 2. Generate branch name
```

REPLACE:
```python
    # 1a. Verify clean working tree (prevent contaminating build branch)
    if await _is_dirty_working_tree(work_dir):
        result.error = (
            "Working tree has uncommitted changes. "
            "Commit or stash changes before running a build."
        )
        return result

    # 1b. AD-458: Pre-flight validation (after clean-tree check, before branch creation)
    pre_flight = getattr(runtime, "pre_flight_runner", None) if runtime is not None else None
    if pre_flight is not None:
        emit = runtime.emit_event if runtime is not None else None
        report = await pre_flight.run(spec, emit_event=emit)
        if not report.passed:
            blocking_failures = [
                r for r in report.results if not r.passed and r.blocking
            ]
            result.error = "pre-flight validation failed: " + ", ".join(
                f"{r.check_name}: {r.detail}" for r in blocking_failures
            )
            return result

    # 2. Generate branch name
```

> Verify-first: `BuildResult` requires `spec` (verified at `builder.py:160-176`). The existing pattern is "construct early at line 2504, mutate `.error`, return" — Section 4 follows that pattern exactly, NOT the `BuildResult(success=False, error=...)` direct-construct form (which would TypeError because `spec` has no default).

---

## Section 5: Add `PreFlightConfig`

**File:** `src/probos/config.py`

```python
class PreFlightConfig(BaseModel):
    """Pre-flight validation configuration (AD-458)."""

    enabled: bool = True
    # AD-458b will add token-budget configuration when LLMTierReachableCheck
    # and TokenBudgetCheck join v2.
```

Wire into `SystemConfig`:

SEARCH:
```python
    engineering: EngineeringConfig = EngineeringConfig()  # AD-457
```

REPLACE:
```python
    engineering: EngineeringConfig = EngineeringConfig()  # AD-457
    pre_flight: PreFlightConfig = PreFlightConfig()  # AD-458
```

> Builder note: this Section 5 sequence assumes AD-457 lands first (Wave 6 build order). Anchor fallback chain (each falls back to the next if predecessor hasn't landed):
> 1. `engineering: EngineeringConfig` (AD-457).
> 2. `validation_framework: ValidationFrameworkConfig` (AD-451).
> 3. `orders: OrdersConfig = OrdersConfig()  # AD-440` — verified at `config.py:1593` as the always-available terminal fallback.

---

## Section 6: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place near the existing AD-451 ReconciliationEscalator block:

```python
    # AD-458: Pre-flight validation runner (v1: 2 checks; LLMTier + TokenBudget deferred to AD-458b)
    if config.pre_flight.enabled:
        from pathlib import Path
        from probos.cognitive.pre_flight import (
            PreFlightRunner,
            TargetFilesExistCheck,
            TargetFilesWritableCheck,
        )
        # finalize.py is at src/probos/startup/finalize.py — four levels deep
        # from the repo root, so parents[3] resolves to the repo root:
        #   parents[0] = src/probos/startup/
        #   parents[1] = src/probos/
        #   parents[2] = src/
        #   parents[3] = repo root  ← target
        repo_root = Path(__file__).resolve().parents[3]
        runtime.pre_flight_runner = PreFlightRunner(
            checks=[
                TargetFilesExistCheck(repo_root=repo_root),
                TargetFilesWritableCheck(repo_root=repo_root),
            ],
        )
        logger.info(
            "AD-458: PreFlightRunner wired (%d checks; LLMTier + TokenBudget deferred to AD-458b)",
            len(runtime.pre_flight_runner.checks),
        )
```

> Verify-first: `runtime.pre_flight_runner` is published as a public attribute (no underscore) per Wave 5 retrospective convention.

---

## Tests

**File:** `tests/test_ad458_pre_flight.py`

10 tests:

1. `test_event_type_preflight_failed_exists` — `EventType.PREFLIGHT_FAILED.value == "preflight_failed"`.
2. `test_pre_flight_config_defaults` — `PreFlightConfig()` defaults: `enabled=True`.
3. `test_target_files_exist_check_passes_when_present` — `tmp_path` fixtures + spec referencing them → `passed=True`.
4. `test_target_files_exist_check_fails_when_missing` — spec with missing file → `passed=False`, detail names the missing file.
5. `test_target_files_exist_check_skips_when_no_target_files` — CREATE-mode spec → `passed=True` with "CREATE mode" detail.
6. `test_target_files_writable_check_detects_readonly` — `tmp_path` file with read-only mode → `passed=False`. (Note: on Windows, `os.access(p, os.W_OK)` is approximate against ACL-protected files; documented in "What This Does NOT Change".)
7. `test_pre_flight_runner_short_circuits_on_blocking_failure` — first check fails blocking → second check NOT called.
8. `test_pre_flight_runner_continues_on_non_blocking_failure` — non-blocking failure recorded but does not abort the run; report.passed reflects only blocking failures.
9. `test_pre_flight_runner_emits_event_on_failure` — failure emits `EventType.PREFLIGHT_FAILED` with `failures` list and aggregate metadata (`started_at`, `completed_at`).
10. `test_pre_flight_check_protocol_is_runtime_checkable` — `isinstance(TargetFilesExistCheck(...), PreFlightCheck)` returns True.

Each test uses `tmp_path` for filesystem fixtures. No shared mutable state. Tests are decorated `@pytest.mark.asyncio` for async paths.

---

## What This Does NOT Change

- `BuilderAgent.act()` is unchanged. AD-458 inserts middleware in `execute_approved_build()` only.
- `BuildSpec` schema is unchanged.
- `BuildResult` schema is unchanged. AD-458 follows the existing create-then-mutate pattern at `builder.py:2504`.
- LLM client interfaces are unchanged. **`LLMTierReachableCheck` is deferred to AD-458b** — needs a public `is_tier_operational(tier_name) -> bool` accessor on `TieredLLMClient` that doesn't exist today (`_tier_status` is private at `cognitive/llm_client.py:100`).
- Token budget enforcement remains in AD-617b (proactive cognitive loop). **`TokenBudgetCheck` is deferred to AD-458b** — soft pre-flight gate would either duplicate AD-617b enforcement or ship as theater.
- No HXI panel.
- No new agent.
- Windows ACL behavior: `os.access(p, os.W_OK)` is approximate against ACL-protected files. v1 catches the common read-only-flag case; ACL-edge-case false positives are documented as accepted tradeoff.

---

## Tracking

- `PROGRESS.md`: add `AD-458 CLOSED. Pre-Flight Validation — ...`
- `docs/development/roadmap.md`: flip AD-458 status from `*(planned)*` to `*(complete)*` near line 4150.
- `DECISIONS.md`: optional entry recording the soft/hard token-budget split (AD-458 soft, AD-617b hard).

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP.

Expected delta:
- `src/probos/cognitive/pre_flight.py`: ~165 lines (new — 2 checks + Protocol + Runner).
- `src/probos/cognitive/builder.py`: ~14 lines added (Section 4 middleware).
- `src/probos/events.py`: 1 line added.
- `src/probos/config.py`: ~6 lines added.
- `src/probos/startup/finalize.py`: ~20 lines added.
- `tests/test_ad458_pre_flight.py`: ~210 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 10 tests pass under `pytest tests/test_ad458_pre_flight.py -v -n 0`.
- Full parallel gate non-decreasing.
- 1 new EventType in `events.py`.
- `runtime.pre_flight_runner` published as public attribute.
- `execute_approved_build()` invokes the runner after the dirty-tree check, before branch creation. Failure isolation: pre-flight failure leaves working tree untouched.
- v1 ships only `TargetFilesExistCheck` and `TargetFilesWritableCheck`. `LLMTierReachableCheck` and `TokenBudgetCheck` are deferred to AD-458b (no v1 theater).
- `PreFlightCheck` Protocol is decorated `@runtime_checkable` so tests can assert via `isinstance`.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
grep -n "class BuildSpec\|class BuilderAgent\|async def execute_approved_build" src/probos/cognitive/builder.py
  146: class BuildSpec:
  1690: class BuilderAgent(CognitiveAgent):
  2482: async def execute_approved_build(

grep -rn "pre_flight\|preflight" src/probos/cognitive/builder.py
  (no matches — AD-458 introduces this middleware)

grep -rn "PreFlightCheck\|PreFlightRunner\|PreFlightResult" src/probos/
  (no matches — AD-458 introduces these names)

grep -n "PREFLIGHT" src/probos/events.py
  (no matches — name is free)

grep -n "engineering: EngineeringConfig" src/probos/config.py
  (added by AD-457 Section 6 — the SEARCH anchor for Section 5)

grep -n "operational_status\|llm_client" src/probos/runtime.py
  (BF-246 health probe surface; AD-458 reads but does not modify)

grep -n "^class BuildResult\b\|self\._tier_status" src/probos/cognitive/builder.py src/probos/cognitive/llm_client.py
  src/probos/cognitive/builder.py:160: class BuildResult:
       (requires `spec: BuildSpec` as 2nd field — Section 4 uses create-then-mutate)
  src/probos/cognitive/llm_client.py:100:    self._tier_status: dict[str, bool] = {}
       (private; no public is_tier_operational accessor today — LLMTierReachableCheck deferred to AD-458b)

grep -n "def emit_event\|orders: OrdersConfig" src/probos/runtime.py src/probos/config.py
  src/probos/runtime.py:775: def emit_event(self, event: ...
  src/probos/config.py:1593: orders: OrdersConfig = OrdersConfig()  # AD-440
       (AD-440 anchor verified as Section 5 terminal fallback)
```

---

## Revision (2026-05-01)

Applied review findings from `prompts/Reviews/ad-458-navigational-deflector-preflight-review.md`.

**Required addressed:**

- **R#1: `BuildResult(success=False, error=...)` TypeError fixed.** Section 4 now uses the existing create-then-mutate pattern (verified at `builder.py:2504`: `result = BuildResult(success=False, spec=spec)`). New SEARCH/REPLACE inserts at `builder.py:2515-2517` (after dirty-tree check, before branch creation).
- **R#2: phantom `client.operational_status.deep` removed.** `LLMTierReachableCheck` deferred wholesale to AD-458b (no theater). v1 ships only `TargetFilesExistCheck` and `TargetFilesWritableCheck`. AD-458b will add the public `is_tier_operational(...)` accessor on `TieredLLMClient` and re-introduce the check.
- **R#3: `Path.parents[3]` explanation rewritten.** Section 6 now shows the parent-level mapping inline (`parents[0] = startup/`, `parents[1] = probos/`, `parents[2] = src/`, `parents[3] = repo root`). No more "3 parents" mistake.
- **R#4: insertion point made explicit.** Section 4 SEARCH/REPLACE block places pre-flight AFTER `_is_dirty_working_tree` check (line 2515) and BEFORE branch generation (line 2517). Failure isolation: working tree stays untouched on pre-flight failure.

**Recommended addressed:**

- **rec#1: `TokenBudgetCheck` deferred wholesale.** Same no-theater rationale as LLMTier — soft check that never reads token state would be documentation-in-code-form.
- **rec#2: Windows ACL limitation documented** in "What This Does NOT Change".
- **rec#3: `PreFlightRunner.checks` immutability** — kept as `list` with note that callers should treat the list as construction-time wiring only. Frozen-tuple form would break the existing `field(default_factory=list)` pattern; keeping list aligns with `PreFlightRunner` being constructed once at startup.
- **rec#4: `PREFLIGHT_FAILED` payload extended** to include `started_at`, `completed_at`, `check_count` for trace completeness.

**Nits applied:**

- nit#1: anchor-chain fallback chain extended to AD-440's `orders: OrdersConfig` (config.py:1593) as terminal fallback (cross-cutting fix #3).
- nit#2: `import os` moved to module-level imports (top of `pre_flight.py`).
- nit#3: Test 8 description clarified ("non-blocking failure recorded but does not abort; report.passed reflects only blocking failures").
- nit#4: TokenBudgetCheck acceptance criterion line dropped (deferred to AD-458b).

**Required #5 / kwargs form:** confirmed safe; flagged for documentation only — no edit needed.

**Verified Against Codebase footer extended:** added `BuildResult` class signature grep, `_tier_status` private accessor grep (proves LLMTier defer is correct), `orders: OrdersConfig` anchor grep.

**v1 scope reduction:** 4 checks → 2 checks. 12 tests → 10 tests. Acceptance criteria updated. AD-458b deferral note added at module-level in `pre_flight.py` so future architects see the planned re-introduction.

**No-theater discipline (cross-cutting fix #1):** applied wholesale. Two checks deferred to AD-458b; v1 ships only checks that do real work today.

**Wave-5 conventions audit (post-revision):** all 6 applied. ✅

**Verdict shift:** Pass-1 ❌ Not Ready → expected ✅ Approved on second-pass review (mechanical fixes, no architectural pivots).
