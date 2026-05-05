# AD-458b — Pre-Flight Validation v2: LLMTier + TokenBudget Checks

**Status:** Drafted, awaiting Builder
**Dependencies:** AD-458 v1 (Wave 6 — pre-flight runner + filesystem checks; COMPLETE), AD-460 v1 (token ledger; COMPLETE), AD-469 v1 (EPS coordinator with `check_budgets()`; COMPLETE), AD-617b v1 (per-agent hourly token budget; COMPLETE).
**Estimated tests:** +12
**Closes:** GH issue #397

## Problem

`src/probos/cognitive/pre_flight.py` ships AD-458 v1 with two filesystem checks (`TargetFilesExistCheck`, `TargetFilesWritableCheck`) and an inline deferral comment at lines 122-128:

```python
# AD-458b deferred:
#   - LLMTierReachableCheck: needs public is_tier_operational(...) accessor on
#     TieredLLMClient (today's _tier_status is private at llm_client.py:100).
#   - TokenBudgetCheck: hard enforcement already lives in AD-617b proactive
#     cognitive loop; a soft pre-flight gate would either duplicate or ship
#     as theater. Defer until AD-617b surface is exercised.
```

Both deferral conditions have cleared at HEAD `a58d0ab`:

1. **LLMTier surface available without new accessor.** `BaseLLMClient.get_health_status()` is a public sync method on the abstract base (`llm_client.py:29-38`). `OpenAICompatibleClient` overrides it to return the cached per-tier `{status, consecutive_failures, last_success, last_failure}` dict. The BF-246 background health probe (`llm_client.py:321-368`) keeps that cache fresh on a 30s interval. AD-458b consumes the public method — no `is_tier_operational()` accessor needs to be added.

2. **Token-budget surface available via AD-469.** `EPSCoordinator.check_budgets()` (`cognitive/eps/coordinator.py:83-92`) is an async public method returning `list[str]` of department names whose share of recent tokens exceeds their allocation. AD-617b shipped 2026-04-13 — the "until AD-617b surface is exercised" condition is satisfied. AD-469's v1 contract returns `[]` (honest deferral until AD-469b's agent→department resolver lands), but the **wiring is the value** — the moment AD-469b changes the contract, the AD-458b check becomes operational without further AD-458b code change.

The build pipeline currently fails LATE on these conditions:

- Architect's deep-tier LLM call times out at 300s instead of failing fast at pre-flight.
- A budget-strained EPS state proceeds into a multi-step build before any signal surfaces.

`runtime.pre_flight_runner` (AD-458 v1 public attribute) is the right place to gate both signals. AD-458b extends `runner.checks` with two new check classes plumbed through `PreFlightConfig`.

## Solution

Three additive edits:

1. **`PreFlightConfig`** — add four new Pydantic fields. Default-True on the two `_check_enabled` flags (wiring is harmless; default-False would silently skip the safety net). Default-False on `token_budget_blocking` (warn-don't-abort until operator confidence builds + AD-469b makes `check_budgets()` meaningful).

2. **`cognitive/pre_flight.py`** — add two module-level check classes after the existing `TargetFilesWritableCheck`. Remove the now-stale 7-line deferral comment.

3. **`startup/finalize.py`** — extend the existing AD-458 if-block to conditionally `.append(...)` the two new checks to `runtime.pre_flight_runner.checks`. Update the log line from "AD-458 ... deferred to AD-458b" to "AD-458b ... wired".

One new test file (`tests/test_ad458b_preflight_v2.py`, 12 tests). Existing 10 AD-458 tests continue to pass unchanged.

## Section 1 — `src/probos/config.py` (add 4 fields, remove TODO)

**File:** `src/probos/config.py`

**SEARCH** (locks the entire `PreFlightConfig` class body verbatim — 5 lines):

```python
class PreFlightConfig(BaseModel):
    """Pre-flight validation configuration (AD-458)."""

    enabled: bool = True
    # AD-458b will add token-budget configuration when LLMTierReachableCheck
    # and TokenBudgetCheck join v2.
```

**REPLACE** (re-emits `enabled` verbatim, removes the TODO comment, appends 4 new fields):

```python
class PreFlightConfig(BaseModel):
    """Pre-flight validation configuration (AD-458 / AD-458b)."""

    enabled: bool = True
    # AD-458b: optional LLM-tier reachability and token-budget checks.
    # Default-True on _check_enabled flags so the wiring is live; the
    # token-budget check is harmless under AD-469 v1 (`check_budgets()`
    # returns `[]`) and activates automatically once AD-469b lands.
    # `token_budget_blocking` defaults False — warn rather than abort
    # until operator confidence builds.
    llm_tier_check_enabled: bool = True
    required_llm_tier: str = "deep"
    token_budget_check_enabled: bool = True
    token_budget_blocking: bool = False
```

## Section 2 — `src/probos/cognitive/pre_flight.py` (add 2 classes, remove 7-line comment)

**File:** `src/probos/cognitive/pre_flight.py`

**SEARCH** (locks the trailing `return` of `TargetFilesWritableCheck.check()`, the deferral comment block, and the opening `@dataclass` of `PreFlightRunner`):

```python
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


@dataclass
class PreFlightRunner:
```

**REPLACE** (re-emits the trailing return verbatim, removes the deferral comment, inserts the two new classes, re-emits the `@dataclass` opening verbatim):

```python
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
```

## Section 3 — `src/probos/startup/finalize.py` (extend AD-458 if-block)

**File:** `src/probos/startup/finalize.py`

**SEARCH** (locks the entire existing AD-458 if-block — 25 lines, from the leading comment through the closing paren of `logger.info`):

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
        #   parents[3] = repo root  <- target
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

**REPLACE** (re-emits the existing two-filesystem-check construction verbatim, conditionally appends the two new checks, updates the log line):

```python
    # AD-458 / AD-458b: Pre-flight validation runner (4 checks at default config)
    if config.pre_flight.enabled:
        from pathlib import Path
        from probos.cognitive.pre_flight import (
            LLMTierReachableCheck,
            PreFlightRunner,
            TargetFilesExistCheck,
            TargetFilesWritableCheck,
            TokenBudgetCheck,
        )
        # finalize.py is at src/probos/startup/finalize.py — four levels deep
        # from the repo root, so parents[3] resolves to the repo root:
        #   parents[0] = src/probos/startup/
        #   parents[1] = src/probos/
        #   parents[2] = src/
        #   parents[3] = repo root  <- target
        repo_root = Path(__file__).resolve().parents[3]
        runtime.pre_flight_runner = PreFlightRunner(
            checks=[
                TargetFilesExistCheck(repo_root=repo_root),
                TargetFilesWritableCheck(repo_root=repo_root),
            ],
        )
        # AD-458b: append LLM-tier and token-budget checks AFTER the cheap
        # filesystem checks. PreFlightRunner short-circuits on the first
        # blocking failure, so the cheapest checks run first.
        if config.pre_flight.llm_tier_check_enabled:
            runtime.pre_flight_runner.checks.append(
                LLMTierReachableCheck(
                    runtime=runtime,
                    required_tier=config.pre_flight.required_llm_tier,
                ),
            )
        if config.pre_flight.token_budget_check_enabled:
            runtime.pre_flight_runner.checks.append(
                TokenBudgetCheck(
                    runtime=runtime,
                    blocking=config.pre_flight.token_budget_blocking,
                ),
            )
        logger.info(
            "AD-458b: PreFlightRunner wired (%d checks)",
            len(runtime.pre_flight_runner.checks),
        )
```

## Section 4 — `tests/test_ad458b_preflight_v2.py` (NEW, 12 tests)

**File:** `tests/test_ad458b_preflight_v2.py` (new)

```python
"""AD-458b: Tests for LLMTierReachableCheck + TokenBudgetCheck."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.pre_flight import (
    LLMTierReachableCheck,
    PreFlightResult,
    TokenBudgetCheck,
)
from probos.config import PreFlightConfig


# ---------------------------------------------------------------------------
# Fakes / fixtures
# ---------------------------------------------------------------------------


class _FakeBuildSpec:
    def __init__(self, title: str = "test build", target_files: list[str] | None = None) -> None:
        self.title = title
        self.target_files = list(target_files or [])


def _make_runtime_with_llm(health: Any) -> SimpleNamespace:
    client = MagicMock()
    client.get_health_status = MagicMock(return_value=health)
    return SimpleNamespace(llm_client=client)


def _make_runtime_with_eps(exceeded: list[str]) -> SimpleNamespace:
    eps = MagicMock()
    eps.check_budgets = AsyncMock(return_value=exceeded)
    return SimpleNamespace(eps_coordinator=eps)


# ---------------------------------------------------------------------------
# Test 1 — PreFlightConfig defaults include AD-458b fields
# ---------------------------------------------------------------------------


def test_pre_flight_config_defaults_includes_new_fields() -> None:
    cfg = PreFlightConfig()
    assert cfg.enabled is True
    assert cfg.llm_tier_check_enabled is True
    assert cfg.required_llm_tier == "deep"
    assert cfg.token_budget_check_enabled is True
    assert cfg.token_budget_blocking is False


# ---------------------------------------------------------------------------
# Tests 2-6 — LLMTierReachableCheck
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_tier_reachable_passes_when_tier_operational() -> None:
    runtime = _make_runtime_with_llm({
        "tiers": {"deep": {"status": "operational"}},
        "overall": "operational",
    })
    check = LLMTierReachableCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert result.check_name == "llm_tier_reachable"
    assert "operational" in result.detail


@pytest.mark.asyncio
async def test_llm_tier_reachable_fails_when_tier_unreachable() -> None:
    runtime = _make_runtime_with_llm({
        "tiers": {"deep": {"status": "unreachable"}},
        "overall": "degraded",
    })
    check = LLMTierReachableCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is False
    assert result.blocking is True
    assert result.detail == "tier 'deep' status: unreachable"


@pytest.mark.asyncio
async def test_llm_tier_reachable_skips_when_no_runtime_client() -> None:
    runtime = SimpleNamespace()  # no llm_client attribute
    check = LLMTierReachableCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert "no llm_client" in result.detail
    assert "skipped" in result.detail


@pytest.mark.asyncio
async def test_llm_tier_reachable_uses_required_tier_from_constructor() -> None:
    runtime = _make_runtime_with_llm({
        "tiers": {
            "fast": {"status": "operational"},
            "deep": {"status": "unreachable"},
        },
        "overall": "degraded",
    })
    check = LLMTierReachableCheck(runtime=runtime, required_tier="fast")
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert "fast" in result.detail


@pytest.mark.asyncio
async def test_llm_tier_reachable_handles_unexpected_health_shape() -> None:
    """Defensive isinstance(dict) guards tolerate stub clients returning None
    or a non-dict from get_health_status()."""
    runtime = _make_runtime_with_llm(None)  # stub returns None
    check = LLMTierReachableCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is False
    assert "unknown" in result.detail


@pytest.mark.asyncio
async def test_llm_tier_reachable_propagates_exception_to_runner() -> None:
    """When client.get_health_status() raises, the exception propagates UP
    to the PreFlightRunner exception envelope (not caught inside check())."""
    client = MagicMock()
    client.get_health_status = MagicMock(side_effect=RuntimeError("boom"))
    runtime = SimpleNamespace(llm_client=client)
    check = LLMTierReachableCheck(runtime=runtime)
    with pytest.raises(RuntimeError):
        await check.check(_FakeBuildSpec())


# ---------------------------------------------------------------------------
# Tests 7-10 — TokenBudgetCheck
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_budget_passes_when_no_eps_coordinator() -> None:
    runtime = SimpleNamespace()  # no eps_coordinator attribute
    check = TokenBudgetCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert "no eps_coordinator" in result.detail
    assert "skipped" in result.detail


@pytest.mark.asyncio
async def test_token_budget_passes_when_check_budgets_empty() -> None:
    """AD-469 v1 contract: check_budgets() returns []. Today's pass case."""
    runtime = _make_runtime_with_eps(exceeded=[])
    check = TokenBudgetCheck(runtime=runtime)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is True
    assert "within budget" in result.detail


@pytest.mark.asyncio
async def test_token_budget_warns_when_budgets_exceeded_default_non_blocking() -> None:
    """AD-469b activation simulation: check_budgets() returns department names.
    Default blocking=False — warning, not abort."""
    runtime = _make_runtime_with_eps(exceeded=["medical", "engineering"])
    check = TokenBudgetCheck(runtime=runtime)  # default blocking=False
    result = await check.check(_FakeBuildSpec())
    assert result.passed is False
    assert result.blocking is False  # warning, not abort
    assert "budgets exceeded" in result.detail
    assert "medical" in result.detail
    assert "engineering" in result.detail


@pytest.mark.asyncio
async def test_token_budget_blocking_flag_makes_failure_blocking() -> None:
    """Operator-tunable: PreFlightConfig.token_budget_blocking=True flips
    the failure to blocking via the constructor `blocking=True`."""
    runtime = _make_runtime_with_eps(exceeded=["science"])
    check = TokenBudgetCheck(runtime=runtime, blocking=True)
    result = await check.check(_FakeBuildSpec())
    assert result.passed is False
    assert result.blocking is True
    assert "science" in result.detail


# ---------------------------------------------------------------------------
# Tests 11-12 — Protocol compliance + integrated runner ordering
# ---------------------------------------------------------------------------


def test_new_checks_satisfy_pre_flight_check_protocol() -> None:
    """Mirrors the AD-458 v1 Protocol-compliance test for the two new checks.

    `PreFlightCheck` is `@runtime_checkable` so concrete implementations
    must satisfy `isinstance(impl, PreFlightCheck)` via duck typing —
    they need `name: str` and `async def check(self, spec) -> PreFlightResult`.
    """
    from probos.cognitive.pre_flight import PreFlightCheck

    runtime = SimpleNamespace()
    llm_check = LLMTierReachableCheck(runtime=runtime)
    tok_check = TokenBudgetCheck(runtime=runtime)
    assert isinstance(llm_check, PreFlightCheck)
    assert isinstance(tok_check, PreFlightCheck)
    assert llm_check.name == "llm_tier_reachable"
    assert tok_check.name == "token_budget"


@pytest.mark.asyncio
async def test_runner_with_all_four_checks_runs_in_expected_order(tmp_path: Path) -> None:
    """End-to-end PreFlightRunner integration: assemble the 4 checks in the
    order finalize.py would produce them, run on a passing spec, assert
    every check fired and the aggregate report.passed is True."""
    from probos.cognitive.pre_flight import (
        PreFlightRunner,
        TargetFilesExistCheck,
        TargetFilesWritableCheck,
    )

    f = tmp_path / "a.py"
    f.write_text("x = 1\n", encoding="utf-8")

    runtime = SimpleNamespace(
        llm_client=MagicMock(get_health_status=MagicMock(return_value={
            "tiers": {"deep": {"status": "operational"}},
            "overall": "operational",
        })),
        eps_coordinator=MagicMock(check_budgets=AsyncMock(return_value=[])),
    )
    runner = PreFlightRunner(checks=[
        TargetFilesExistCheck(repo_root=tmp_path),
        TargetFilesWritableCheck(repo_root=tmp_path),
        LLMTierReachableCheck(runtime=runtime),
        TokenBudgetCheck(runtime=runtime),
    ])
    spec = _FakeBuildSpec(target_files=["a.py"])
    report = await runner.run(spec)

    assert report.passed is True
    assert len(report.results) == 4
    assert [r.check_name for r in report.results] == [
        "target_files_exist",
        "target_files_writable",
        "llm_tier_reachable",
        "token_budget",
    ]
    assert all(r.passed for r in report.results)
```

## What This Does NOT Change

- **`BaseLLMClient` and `OpenAICompatibleClient`** are not modified. The check consumes the existing public `get_health_status()` method.
- **`EPSCoordinator`** is not modified. The check consumes the existing public `check_budgets()` method (returns `[]` in v1; activates with AD-469b).
- **`PreFlightRunner`** is not modified. New checks plug into `runner.checks` via the existing mutable list field.
- **`runtime.pre_flight_runner`** public attribute name is unchanged. No new runtime attribute is added.
- **No new EventType.** `EventType.PREFLIGHT_FAILED` is reused via the existing runner emit path.
- **No new file beyond the test file.** The two new check classes live in the existing `cognitive/pre_flight.py`.
- **No live LLM probe.** `LLMTierReachableCheck` reads the cached health-status; the BF-246 background probe is the freshness mechanism. AD-458b does NOT call `client.check_connectivity()` (that does a live network probe; would add 5-15s per build).
- **No bypass of `check_budgets()`.** The check is a thin wrapper over the public async method; no read of `eps._budgets` or any private attribute.
- **No private-attr access on the LLM client.** `_tier_status` is NOT read directly (Wave-5 convention #2 compliance).
- **No agent-level token budgeting.** AD-617b owns per-agent enforcement at runtime; AD-458b only gates the build cycle on the coarser EPS-department signal. Per-agent integration is AD-458b-3.
- **No HXI surface.** Pre-flight summaries already flow through `PREFLIGHT_FAILED` events — HXI consumption is AD-458b-4.
- **No federation pre-flight.** AD-458 Roadmap section 3 (sender trust + message schema validation for federated messages) is AD-458b-5.
- **No commercial overlay.** SLA-graded pre-flight (per-tenant tier reachability SLOs, regulator-facing pre-flight evidence chain) is AD-458b-6 *(Commercial)*.
- **No default-True flip on `token_budget_blocking`.** That happens after AD-469b lands and operator confidence builds — AD-458b-1.

## Tracking

- **PROGRESS.md** — append a new "AD-458b CLOSED" entry on the same line pattern as Wave 59's AD-528c entry.
- **docs/development/roadmap.md** line 4158 — flip status from `*(Scoped, OSS, Issue #397)*` to `*(complete, OSS, Issue #397)*`.
- **GH issue #397** — close with the commit hash.
- **DECISIONS.md** — no new entry required (this is a deferred-completion of AD-458; the Decision Log entries live in this prompt's parent dispatch and the build report).

## Acceptance Criteria

- All 12 tests in `tests/test_ad458b_preflight_v2.py` pass.
- All 10 tests in `tests/test_ad458_pre_flight.py` continue to pass unchanged.
- `LLMTierReachableCheck` and `TokenBudgetCheck` both satisfy `isinstance(impl, PreFlightCheck)` (test #11).
- `LLMTierReachableCheck` reads ONLY `client.get_health_status()` — `grep -n "_tier_status" src/probos/cognitive/pre_flight.py` returns 0 hits.
- `TokenBudgetCheck` reads ONLY `eps.check_budgets()` — `grep -n "_budgets\b" src/probos/cognitive/pre_flight.py` returns 0 hits.
- The deferral comment block at `pre_flight.py:122-128` is removed; `grep -n "AD-458b deferred" src/probos/cognitive/pre_flight.py` returns 0 hits.
- The startup log message string in `finalize.py` reads `"AD-458b: PreFlightRunner wired (%d checks)"` (the `%d` resolves to 4 under default `SystemConfig()`); `grep -n "AD-458b: PreFlightRunner wired" src/probos/startup/finalize.py` returns 1 hit.
- `runtime.pre_flight_runner.checks` is constructed with 2 filesystem checks then conditionally extended via `.append(...)` for each of the two new checks based on `config.pre_flight.{llm_tier_check_enabled,token_budget_check_enabled}` flags; `grep -n "runtime.pre_flight_runner.checks.append" src/probos/startup/finalize.py` returns at least 2 hits.
- Full gate (`pytest tests/ -q -n 8 --dist=loadfile`) reports **11303 passed** (delta +12 vs Wave 59 baseline 11291).
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

## Verified Against Codebase (2026-05-05, HEAD `a58d0ab`)

```
grep -n "class PreFlightConfig" src/probos/config.py
  1250: class PreFlightConfig(BaseModel):

grep -n "pre_flight: PreFlightConfig" src/probos/config.py
  2324:     pre_flight: PreFlightConfig = PreFlightConfig()  # AD-458

grep -n "AD-458b deferred" src/probos/cognitive/pre_flight.py
  122: # AD-458b deferred:

grep -n "class TargetFilesWritableCheck" src/probos/cognitive/pre_flight.py
  90: class TargetFilesWritableCheck:

grep -n "@dataclass$" src/probos/cognitive/pre_flight.py
  131: @dataclass

grep -n "class PreFlightRunner" src/probos/cognitive/pre_flight.py
  136: class PreFlightRunner:

grep -n "def get_health_status" src/probos/cognitive/llm_client.py
  29:     def get_health_status(self) -> dict[str, Any]:

grep -n "self._tier_status" src/probos/cognitive/llm_client.py
  105:         self._tier_status: dict[str, bool] = {}

grep -n "class EPSCoordinator" src/probos/cognitive/eps/coordinator.py
  24: class EPSCoordinator:

grep -n "async def check_budgets" src/probos/cognitive/eps/coordinator.py
  83:     async def check_budgets(self) -> list[str]:

grep -n "AD-458: Pre-flight" src/probos/startup/finalize.py
  1102:     # AD-458: Pre-flight validation runner (v1: 2 checks; LLMTier + TokenBudget deferred to AD-458b)

grep -n "runtime.pre_flight_runner = PreFlightRunner" src/probos/startup/finalize.py
  1116:         runtime.pre_flight_runner = PreFlightRunner(

grep -n "PreFlightRunner wired" src/probos/startup/finalize.py
  1123:             "AD-458: PreFlightRunner wired (%d checks; LLMTier + TokenBudget deferred to AD-458b)",

grep -n "PREFLIGHT_FAILED" src/probos/events.py
  200:     PREFLIGHT_FAILED = "preflight_failed"  # AD-458

grep -n "pre_flight = getattr" src/probos/cognitive/builder.py
  2518:     pre_flight = getattr(runtime, "pre_flight_runner", None) if runtime is not None else None

grep -rn "class LLMTierReachableCheck" src/probos/
  (no hits — net-new symbol; intra-prompt-introduction in Section 2)

grep -rn "class TokenBudgetCheck" src/probos/
  (no hits — net-new symbol; intra-prompt-introduction in Section 2)

grep -rn "llm_tier_check_enabled" src/probos/
  (no hits — net-new field; intra-prompt-introduction in Section 1)

grep -rn "required_llm_tier" src/probos/
  (no hits — net-new field; intra-prompt-introduction in Section 1)

grep -rn "token_budget_check_enabled" src/probos/
  (no hits — net-new field; intra-prompt-introduction in Section 1)

grep -rn "token_budget_blocking" src/probos/
  (no hits — net-new field; intra-prompt-introduction in Section 1)

grep -n "test_pre_flight_config_defaults" tests/test_ad458_pre_flight.py
  46: def test_pre_flight_config_defaults() -> None:

grep -rn "tests/test_ad458b" tests/
  (no hits — net-new file; intra-prompt-introduction in Section 4)

grep -n "_UNREACHABLE_THRESHOLD" src/probos/cognitive/llm_client.py
  59:     _UNREACHABLE_THRESHOLD = 3  # BF-069: consecutive failures before tier is unreachable
```
