"""AD-458: Navigational Deflector — Pre-Flight Validation.

Middleware between build approval and execution. Validates that the
build path is clear before the BuilderAgent commits expensive resources
(LLM calls, file writes). Mirrors the AD-446 CompensationHandler shape:
a small handler invoked by the existing pipeline, not a re-architecture.
"""

from __future__ import annotations

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


@runtime_checkable
class PreFlightCheck(Protocol):
    """Protocol for a single pre-flight check.

    Implementations must be async (some checks need I/O — file stat). They
    must NOT mutate any state. Decorated `@runtime_checkable` so tests can
    assert via `isinstance(impl, PreFlightCheck)`.
    """

    name: str

    async def check(self, spec: "BuildSpec") -> PreFlightResult:
        ...


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


# ---------------------------------------------------------------------------
# AD-458b: LLM tier reachability and token-budget pre-flight checks.
# Both check classes consume existing public surfaces only:
#   - LLMTierReachableCheck reads BaseLLMClient.get_health_status() (cached;
#     refreshed on a 30s interval by the BF-246 background probe).
#   - TokenBudgetCheck reads EPSCoordinator.check_budgets() (AD-469 v1;
#     returns [] until AD-469b lands the agent->department resolver).
# Neither check probes the network nor mutates state.
# ---------------------------------------------------------------------------


class LLMTierReachableCheck:
    """Verify the configured LLM tier reports operational status (AD-458b).

    Consumes the public `BaseLLMClient.get_health_status()` cache rather than
    issuing a live probe. The cache is maintained by the BF-246 background
    health probe (30s interval). Default `required_tier='deep'` because the
    Architect's proposal generation is the highest-risk LLM dependency in
    the build cycle. Operator can switch to 'fast' or 'standard' via
    `PreFlightConfig.required_llm_tier`.

    blocking=True (default): a build that depends on the LLM tier should
    not proceed when the tier is reported unreachable.
    """

    name = "llm_tier_reachable"

    def __init__(self, *, runtime: Any, required_tier: str = "deep") -> None:
        self._runtime = runtime
        self._required_tier = required_tier

    async def check(self, spec: "BuildSpec") -> PreFlightResult:
        client = getattr(self._runtime, "llm_client", None)
        if client is None:
            return PreFlightResult(
                passed=True, check_name=self.name,
                detail="no llm_client (skipped)",
            )
        health = client.get_health_status()
        tiers = health.get("tiers", {}) if isinstance(health, dict) else {}
        tier_info = tiers.get(self._required_tier, {}) if isinstance(tiers, dict) else {}
        status = tier_info.get("status", "unknown") if isinstance(tier_info, dict) else "unknown"
        if status == "operational":
            return PreFlightResult(
                passed=True, check_name=self.name,
                detail=f"tier '{self._required_tier}' operational",
            )
        return PreFlightResult(
            passed=False, check_name=self.name,
            detail=f"tier '{self._required_tier}' status: {status}",
        )


class TokenBudgetCheck:
    """Verify EPS department budgets are within allocation (AD-458b).

    Thin wrapper over the public `EPSCoordinator.check_budgets()` method.
    Under AD-469 v1, `check_budgets()` returns `[]` (honest deferral until
    AD-469b's agent->department resolver lands); this check is therefore
    a no-op today but the wiring is live so the gate activates the moment
    AD-469b changes the contract.

    blocking=False (default): a budget overrun is a rate-of-spend signal,
    not a hard correctness signal. Warn rather than abort. Operator can
    flip via `PreFlightConfig.token_budget_blocking` once confidence
    builds and AD-469b is in production.
    """

    name = "token_budget"

    def __init__(self, *, runtime: Any, blocking: bool = False) -> None:
        self._runtime = runtime
        self._blocking = blocking

    async def check(self, spec: "BuildSpec") -> PreFlightResult:
        eps = getattr(self._runtime, "eps_coordinator", None)
        if eps is None:
            return PreFlightResult(
                passed=True, check_name=self.name,
                detail="no eps_coordinator (skipped)",
            )
        exceeded: list[str] = await eps.check_budgets()
        if not exceeded:
            return PreFlightResult(
                passed=True, check_name=self.name,
                detail="all departments within budget",
            )
        return PreFlightResult(
            passed=False, check_name=self.name,
            detail=f"budgets exceeded: {', '.join(exceeded[:5])}",
            blocking=self._blocking,
        )


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
