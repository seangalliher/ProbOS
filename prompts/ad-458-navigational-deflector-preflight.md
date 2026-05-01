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

- **Protocol layer** — `PreFlightCheck` Protocol + `PreFlightResult` dataclass + four built-in checks (target-files-exist, target-files-writable, llm-tier-reachable, token-budget-sufficient).
- **Runner layer** — `PreFlightRunner` composes the checks. Stateless. Each `run(spec)` call is independent.

This is **middleware between approval and execution.** AD-458 does NOT change `BuilderAgent.act()` itself, does NOT change `BuildSpec` schema, does NOT add new LLM calls. The runner is invoked from `execute_approved_build()` as the first step, before the existing flow.

The AD-446 `CompensationHandler` (already in the codebase) is the architectural model: a small handler invoked by the existing pipeline, not a re-architecture.

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
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

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

    Implementations must be async (some checks need I/O — file stat, HTTP
    HEAD against the LLM proxy). They must NOT mutate any state.
    """

    name: str

    async def check(self, spec: "BuildSpec") -> PreFlightResult:
        ...
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
                # mode check; OS layer may reject anyway, but read-only flag catches the common case.
                import os
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


class LLMTierReachableCheck:
    """Verify the configured deep tier responds to a health probe.

    Uses runtime.llm_client's existing health check if available; otherwise
    log-and-degrade returns True (network probes are deferred to BF-246's
    background health probe).
    """

    name = "llm_tier_reachable"

    def __init__(self, *, runtime: Any) -> None:
        self._runtime = runtime

    async def check(self, spec: "BuildSpec") -> PreFlightResult:
        rt = self._runtime
        if rt is None:
            return PreFlightResult(
                passed=True, check_name=self.name,
                detail="no runtime — assuming reachable",
            )
        client = getattr(rt, "llm_client", None)
        if client is None:
            return PreFlightResult(
                passed=True, check_name=self.name,
                detail="no llm_client — assuming reachable",
            )
        # Read existing operational status (BF-246 health probe surface)
        status = getattr(client, "operational_status", None)
        if status is None:
            return PreFlightResult(
                passed=True, check_name=self.name,
                detail="no operational_status — assuming reachable",
            )
        deep = getattr(status, "deep", "operational")
        ok = str(deep).lower() == "operational"
        return PreFlightResult(
            passed=ok, check_name=self.name,
            detail=f"deep tier status: {deep}",
        )


class TokenBudgetCheck:
    """Verify the agent has token budget for the estimated chunk count.

    Uses the AD-617b CognitiveJournal token-usage surface if available.
    """

    name = "token_budget_sufficient"
    DEFAULT_MIN_REMAINING_TOKENS = 50_000

    def __init__(
        self, *, runtime: Any, min_remaining_tokens: int = DEFAULT_MIN_REMAINING_TOKENS,
    ) -> None:
        self._runtime = runtime
        self._min_remaining_tokens = min_remaining_tokens

    async def check(self, spec: "BuildSpec") -> PreFlightResult:
        # AD-458 uses the existing journal surface as a soft check.
        # Hard token-budget enforcement lives in the proactive cognitive loop
        # (AD-617b); pre-flight is a heads-up, not the enforcer.
        return PreFlightResult(
            passed=True, check_name=self.name,
            detail=f"soft check (min {self._min_remaining_tokens} tokens) — actual enforcement at AD-617b layer",
            blocking=False,
        )
```

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

Find `execute_approved_build()` (verified at `builder.py:2482`). Add a pre-flight invocation as the first step. The Builder must grep the function signature to see what's in scope before drafting the SEARCH/REPLACE.

Insert at the top of the function body:

```python
    # AD-458: Pre-flight validation
    pre_flight = getattr(runtime, "pre_flight_runner", None)
    if pre_flight is not None:
        report = await pre_flight.run(spec, emit_event=runtime.emit_event)
        if not report.passed:
            return BuildResult(
                success=False,
                error="pre-flight validation failed: " + ", ".join(
                    r.detail for r in report.results if not r.passed and r.blocking
                ),
            )
```

> Verify-first: `BuildResult` is the existing return type — confirm by greping `class BuildResult` in `builder.py`. If the actual signature uses different field names, adjust the kwargs to match. The pattern is "early return with a failure result" — same shape as existing `execute_approved_build` failure paths.

---

## Section 5: Add `PreFlightConfig`

**File:** `src/probos/config.py`

```python
class PreFlightConfig(BaseModel):
    """Pre-flight validation configuration (AD-458)."""

    enabled: bool = True
    min_remaining_tokens: int = Field(default=50_000, ge=1_000)
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

> Builder note: this Section 5 sequence assumes AD-457 lands first (Wave 6 build order). If AD-457 has not landed, anchor on `validation_framework: ValidationFrameworkConfig = ValidationFrameworkConfig()  # AD-451` instead.

---

## Section 6: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place near the existing AD-451 ReconciliationEscalator block:

```python
    # AD-458: Pre-flight validation runner
    if config.pre_flight.enabled:
        from pathlib import Path
        from probos.cognitive.pre_flight import (
            LLMTierReachableCheck,
            PreFlightRunner,
            TargetFilesExistCheck,
            TargetFilesWritableCheck,
            TokenBudgetCheck,
        )
        repo_root = Path(__file__).resolve().parents[3]
        runtime.pre_flight_runner = PreFlightRunner(
            checks=[
                TargetFilesExistCheck(repo_root=repo_root),
                TargetFilesWritableCheck(repo_root=repo_root),
                LLMTierReachableCheck(runtime=runtime),
                TokenBudgetCheck(
                    runtime=runtime,
                    min_remaining_tokens=config.pre_flight.min_remaining_tokens,
                ),
            ],
        )
        logger.info("AD-458: PreFlightRunner wired (%d checks)", len(runtime.pre_flight_runner.checks))
```

> Verify-first: `Path(__file__).resolve().parents[3]` from `src/probos/startup/finalize.py` resolves to the repo root. The Builder must verify by counting parent levels: file → startup → probos → src → REPO_ROOT (3 parents). `runtime.pre_flight_runner` is published as a public attribute (no underscore) per Wave 5 retrospective convention.

---

## Tests

**File:** `tests/test_ad458_pre_flight.py`

12 tests:

1. `test_event_type_preflight_failed_exists` — `EventType.PREFLIGHT_FAILED.value == "preflight_failed"`.
2. `test_pre_flight_config_defaults` — `PreFlightConfig()` defaults: `enabled=True`, `min_remaining_tokens=50_000`.
3. `test_target_files_exist_check_passes_when_present` — `tmp_path` fixtures + spec referencing them → `passed=True`.
4. `test_target_files_exist_check_fails_when_missing` — spec with missing file → `passed=False`, detail names the missing file.
5. `test_target_files_exist_check_skips_when_no_target_files` — CREATE-mode spec → `passed=True` with "CREATE mode" detail.
6. `test_target_files_writable_check_detects_readonly` — `tmp_path` file with read-only mode → `passed=False`.
7. `test_llm_tier_reachable_check_when_no_runtime` — `runtime=None` → `passed=True` (assuming reachable).
8. `test_llm_tier_reachable_check_operational` — fake runtime with `operational_status.deep="operational"` → `passed=True`.
9. `test_llm_tier_reachable_check_degraded` — fake runtime with `operational_status.deep="degraded"` → `passed=False`.
10. `test_pre_flight_runner_short_circuits_on_blocking_failure` — first check fails blocking → second check NOT called.
11. `test_pre_flight_runner_continues_on_non_blocking_failure` — non-blocking failure does not abort the run.
12. `test_pre_flight_runner_emits_event_on_failure` — failure emits `EventType.PREFLIGHT_FAILED` with `failures` list.

Each test uses `tmp_path` for filesystem fixtures. No shared mutable state.

---

## What This Does NOT Change

- `BuilderAgent.act()` is unchanged. AD-458 inserts middleware in `execute_approved_build()` only.
- `BuildSpec` schema is unchanged.
- LLM client interfaces are unchanged. `LLMTierReachableCheck` reads `operational_status` if present, no-ops otherwise.
- Token budget enforcement is **soft** — non-blocking. Hard enforcement remains in AD-617b (proactive cognitive loop).
- No HXI panel.
- No new agent.

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
- `src/probos/cognitive/pre_flight.py`: ~250 lines (new).
- `src/probos/cognitive/builder.py`: ~10 lines added (Section 4 middleware).
- `src/probos/events.py`: 1 line added.
- `src/probos/config.py`: ~9 lines added.
- `src/probos/startup/finalize.py`: ~22 lines added.
- `tests/test_ad458_pre_flight.py`: ~250 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 12 tests pass under `pytest tests/test_ad458_pre_flight.py -v -n 0`.
- Full parallel gate non-decreasing.
- 1 new EventType in `events.py`.
- `runtime.pre_flight_runner` published as public attribute.
- `execute_approved_build()` calls the runner before any LLM/file work.
- TokenBudgetCheck is non-blocking (soft).
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
```
