# AD-451: Validation Framework Hardening

**Status:** Ready for builder
**Dependencies:** None hard. Builds on existing `RedTeamAgent.verify(...)` (`src/probos/agents/red_team.py:66`) and `SystemQAAgent.run_smoke_tests(...)` (`src/probos/agents/system_qa.py:236`). Coordinates with the AD-455b deferred-dispatch design.
**Estimated tests:** ~14
**Risk:** High — cross-cutting validation surface that consensus paths consult; touches red-team verification API and adds reconciliation escalation gating. Must respect destructive-intent consensus rules.

---

## Problem

ProbOS already has two validation surfaces:

- `RedTeamAgent.verify(target_agent_id, intent, claimed_result) -> VerificationResult` at `src/probos/agents/red_team.py:66`. Re-executes the same operation, compares output, returns confidence + discrepancy.
- `SystemQAAgent.run_smoke_tests(...)` at `src/probos/agents/system_qa.py:236`. Independent verification campaigns.

What is missing:

1. **Two-stage outcome verification** — metadata scan first (cheap), live re-execution second (expensive) only when metadata mismatches or confidence is below a threshold. Today every `verify()` does both.
2. **Inline per-action self-verification** — agents do not have a hook to check their own work between `act()` and `report()`.
3. **Reconciliation escalation protocol** — when two verifiers disagree, no structured path: confidence comparison → independent verification → arbitrated outcome.

`grep -rn "ValidationFramework\|reconciliation_escalation\|two_stage_verify" src/probos/` returns no matches — none of these surfaces exist.

## Solution Overview

Add `src/probos/cognitive/validation_framework.py` (new) with three small additions:

1. **`TwoStageVerifier`** — wraps an existing `RedTeamAgent`. First call does metadata-only check (file size, hash, return-value type); only escalates to live re-execution when metadata is inconclusive.
2. **`SelfVerificationHook`** — a small protocol that agents may implement; `CognitiveAgent.act()` callers can invoke it between `act()` and `report()`.
3. **`ReconciliationEscalator`** — when two `VerificationResult`s disagree on the same `(target_agent_id, intent)`, pick the higher-confidence verdict; if both are high-confidence and disagree, escalate to a third independent verification through the existing red-team pool. Records every escalation as `EventType.VALIDATION_RECONCILIATION_REQUESTED`.

This is **policy + diagnostics layered on existing surfaces.** AD-451 does NOT redesign `RedTeamAgent.verify()`, does NOT add a new agent pool, does NOT change consensus voting weights. It composes existing primitives into stricter outcome-verification flows.

The `verify(...)` API is left unchanged. AD-455b's deferred adversarial-dispatch design references `verify(...)` as-is; AD-451 does not interact with that deferred work.

---

## Section 0: Event Types

Add to `src/probos/events.py` near the existing security/diagnostic block:

```
VALIDATION_RECONCILIATION_REQUESTED = "validation_reconciliation_requested"  # AD-451
VALIDATION_OUTCOME_VERIFIED = "validation_outcome_verified"  # AD-451
```

Two new values. Verified absent via `grep -n "VALIDATION_RECONCILIATION\|VALIDATION_OUTCOME" src/probos/events.py` (no matches).

---

## Section 1: `TwoStageVerifier`

**File:** `src/probos/cognitive/validation_framework.py` (new)

```python
"""AD-451: Validation Framework Hardening.

Layered policies over existing RedTeamAgent.verify() and SystemQAAgent.
Does NOT change those APIs. Composes existing primitives into stricter
outcome-verification flows.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from probos.events import EventType

if TYPE_CHECKING:
    from probos.agents.red_team import RedTeamAgent
    from probos.types import IntentMessage, IntentResult, VerificationResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TwoStageOutcome:
    """Result of a two-stage verification."""

    verified: bool
    metadata_only: bool       # True if live re-execution was skipped
    metadata_confidence: float
    live_confidence: float    # 0.0 if live stage was skipped
    discrepancy: str
    target_agent_id: str
    intent_id: str
    completed_at: float


class TwoStageVerifier:
    """Wraps a RedTeamAgent. Metadata first, live only when ambiguous.

    Stateless. Each verify() call is independent. Caller is responsible
    for selecting the RedTeamAgent instance.
    """

    DEFAULT_METADATA_THRESHOLD = 0.85

    def __init__(
        self,
        *,
        red_team: "RedTeamAgent",
        emit_event: Any | None = None,
        metadata_threshold: float = DEFAULT_METADATA_THRESHOLD,
    ) -> None:
        self._red_team = red_team
        self._emit_event = emit_event
        self._metadata_threshold = metadata_threshold

    async def verify(
        self,
        *,
        target_agent_id: str,
        intent: "IntentMessage",
        claimed: "IntentResult",
    ) -> TwoStageOutcome:
        """Two-stage verification. Returns TwoStageOutcome regardless of path."""
        meta = self._metadata_check(intent, claimed)
        now = time.time()

        if meta.confidence >= self._metadata_threshold and not meta.discrepancy:
            outcome = TwoStageOutcome(
                verified=True,
                metadata_only=True,
                metadata_confidence=meta.confidence,
                live_confidence=0.0,
                discrepancy="",
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                completed_at=now,
            )
            self._emit(outcome)
            return outcome

        live = await self._red_team.verify(
            target_agent_id=target_agent_id,
            intent=intent,
            claimed_result=claimed,
        )
        outcome = TwoStageOutcome(
            verified=live.verified,
            metadata_only=False,
            metadata_confidence=meta.confidence,
            live_confidence=live.confidence,
            discrepancy=live.discrepancy or meta.discrepancy,
            target_agent_id=target_agent_id,
            intent_id=intent.id,
            completed_at=time.time(),
        )
        self._emit(outcome)
        return outcome

    @dataclass(frozen=True)
    class _MetadataCheck:
        confidence: float
        discrepancy: str

    def _metadata_check(
        self,
        intent: "IntentMessage",
        claimed: "IntentResult",
    ) -> "TwoStageVerifier._MetadataCheck":
        """Cheap metadata check. Subclass overrides for domain-specific signals.

        Default implementation: presence of result, agent_id match, no error.
        Returns 0.95 confidence on full pass; 0.30 with a discrepancy hint.
        """
        if not claimed:
            return TwoStageVerifier._MetadataCheck(0.0, "no result")
        if getattr(claimed, "error", None):
            return TwoStageVerifier._MetadataCheck(
                0.30, f"error reported: {claimed.error}",
            )
        if not getattr(claimed, "success", True):
            return TwoStageVerifier._MetadataCheck(0.30, "success=False")
        return TwoStageVerifier._MetadataCheck(0.95, "")

    def _emit(self, outcome: TwoStageOutcome) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.VALIDATION_OUTCOME_VERIFIED,
                {
                    "verified": outcome.verified,
                    "metadata_only": outcome.metadata_only,
                    "metadata_confidence": outcome.metadata_confidence,
                    "live_confidence": outcome.live_confidence,
                    "target_agent_id": outcome.target_agent_id,
                    "intent_id": outcome.intent_id,
                },
            )
        except Exception:
            logger.warning("AD-451: VALIDATION_OUTCOME_VERIFIED emit failed", exc_info=True)
```

---

## Section 2: `SelfVerificationHook` protocol

**File:** `src/probos/cognitive/validation_framework.py` (continued)

```python
class SelfVerificationHook(Protocol):
    """Optional protocol — agents may implement to self-check between act() and report().

    Returns (passed: bool, reason: str). False causes the caller to skip
    `report()` and surface a discrepancy. The hook is purely advisory; the
    caller decides what to do with a False result. v1 callers: none —
    AD-451 ships the protocol; AD-451b would wire it into CognitiveAgent.
    """

    async def self_verify(self, intent: Any, result: Any) -> tuple[bool, str]:
        ...
```

> Builder note: this is the protocol declaration only. Wiring into `CognitiveAgent.act()` flow is deferred to AD-451b — AD-451 ships the validation framework primitives without modifying the cognitive lifecycle.

---

## Section 3: `ReconciliationEscalator`

**File:** `src/probos/cognitive/validation_framework.py` (continued)

```python
@dataclass(frozen=True)
class ReconciliationOutcome:
    """Outcome of a verification reconciliation."""

    resolved: bool
    chosen_verdict: bool      # The verdict the escalator picked
    primary_confidence: float
    secondary_confidence: float
    third_invoked: bool
    target_agent_id: str
    intent_id: str
    reason: str


class ReconciliationEscalator:
    """Resolves disagreements between two verifiers on the same outcome.

    Algorithm:
    - If confidence delta > min_confidence_delta, accept the higher-confidence verdict.
    - Otherwise invoke a third independent RedTeamAgent and majority-vote.
    - If only one RedTeamAgent is available (red_team_agents pool is small),
      log-and-degrade: accept the higher-confidence verdict regardless of delta.

    No mutation of trust; reconciliation outcomes are diagnostic only.
    """

    MIN_CONFIDENCE_DELTA = 0.20

    def __init__(
        self,
        *,
        runtime: Any,
        emit_event: Any | None = None,
        min_confidence_delta: float = MIN_CONFIDENCE_DELTA,
    ) -> None:
        self._runtime = runtime
        self._emit_event = emit_event
        self._min_confidence_delta = min_confidence_delta

    async def reconcile(
        self,
        *,
        target_agent_id: str,
        intent: "IntentMessage",
        claimed: "IntentResult",
        primary: "VerificationResult",
        secondary: "VerificationResult",
    ) -> ReconciliationOutcome:
        if primary.verified == secondary.verified:
            return ReconciliationOutcome(
                resolved=True,
                chosen_verdict=primary.verified,
                primary_confidence=primary.confidence,
                secondary_confidence=secondary.confidence,
                third_invoked=False,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                reason="agreement",
            )

        delta = abs(primary.confidence - secondary.confidence)
        if delta >= self._min_confidence_delta:
            verdict = primary.verified if primary.confidence > secondary.confidence else secondary.verified
            outcome = ReconciliationOutcome(
                resolved=True,
                chosen_verdict=verdict,
                primary_confidence=primary.confidence,
                secondary_confidence=secondary.confidence,
                third_invoked=False,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                reason="confidence_delta",
            )
            self._emit(outcome)
            return outcome

        third = await self._invoke_third(target_agent_id, intent, claimed)
        if third is None:
            verdict = primary.verified if primary.confidence > secondary.confidence else secondary.verified
            outcome = ReconciliationOutcome(
                resolved=True,
                chosen_verdict=verdict,
                primary_confidence=primary.confidence,
                secondary_confidence=secondary.confidence,
                third_invoked=False,
                target_agent_id=target_agent_id,
                intent_id=intent.id,
                reason="third_unavailable",
            )
            self._emit(outcome)
            return outcome

        votes = sum([primary.verified, secondary.verified, third.verified])
        majority = votes >= 2
        outcome = ReconciliationOutcome(
            resolved=True,
            chosen_verdict=majority,
            primary_confidence=primary.confidence,
            secondary_confidence=secondary.confidence,
            third_invoked=True,
            target_agent_id=target_agent_id,
            intent_id=intent.id,
            reason="majority_vote",
        )
        self._emit(outcome)
        return outcome

    async def _invoke_third(
        self,
        target_agent_id: str,
        intent: "IntentMessage",
        claimed: "IntentResult",
    ) -> "VerificationResult | None":
        agents = list(getattr(self._runtime, "red_team_agents", []) or [])
        if len(agents) < 3:
            return None
        third = agents[2]
        try:
            return await third.verify(
                target_agent_id=target_agent_id,
                intent=intent,
                claimed_result=claimed,
            )
        except Exception:
            logger.warning("AD-451: third-verifier invocation failed", exc_info=True)
            return None

    def _emit(self, outcome: ReconciliationOutcome) -> None:
        if not self._emit_event:
            return
        try:
            self._emit_event(
                EventType.VALIDATION_RECONCILIATION_REQUESTED,
                {
                    "resolved": outcome.resolved,
                    "chosen_verdict": outcome.chosen_verdict,
                    "primary_confidence": outcome.primary_confidence,
                    "secondary_confidence": outcome.secondary_confidence,
                    "third_invoked": outcome.third_invoked,
                    "target_agent_id": outcome.target_agent_id,
                    "intent_id": outcome.intent_id,
                    "reason": outcome.reason,
                },
            )
        except Exception:
            logger.warning(
                "AD-451: VALIDATION_RECONCILIATION_REQUESTED emit failed",
                exc_info=True,
            )
```

---

## Section 4: Add EventTypes

**File:** `src/probos/events.py`

SEARCH:
```python
    AGENT_SELF_NAMED = "agent_self_named"  # AD-499
```

REPLACE:
```python
    AGENT_SELF_NAMED = "agent_self_named"  # AD-499
    VALIDATION_RECONCILIATION_REQUESTED = "validation_reconciliation_requested"  # AD-451
    VALIDATION_OUTCOME_VERIFIED = "validation_outcome_verified"  # AD-451
```

---

## Section 5: Add `ValidationFrameworkConfig`

**File:** `src/probos/config.py`

```python
class ValidationFrameworkConfig(BaseModel):
    """Validation framework configuration (AD-451)."""

    enabled: bool = True
    metadata_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    min_confidence_delta: float = Field(default=0.20, ge=0.0, le=1.0)
```

Wire into `SystemConfig`:

SEARCH:
```python
    orders: OrdersConfig = OrdersConfig()  # AD-440
```

REPLACE:
```python
    orders: OrdersConfig = OrdersConfig()  # AD-440
    validation_framework: ValidationFrameworkConfig = ValidationFrameworkConfig()  # AD-451
```

---

## Section 6: Wire into startup

**File:** `src/probos/startup/finalize.py`

Place near the existing AD-440 OrderManager block:

```python
    # AD-451: Validation Framework
    if config.validation_framework.enabled:
        from probos.cognitive.validation_framework import (
            ReconciliationEscalator,
            TwoStageVerifier,
        )
        # TwoStageVerifier requires a specific red_team agent — defer instance
        # construction to per-call sites. Wire only the ReconciliationEscalator
        # (no per-call agent dependency).
        runtime.reconciliation_escalator = ReconciliationEscalator(
            runtime=runtime,
            emit_event=runtime.emit_event,
            min_confidence_delta=config.validation_framework.min_confidence_delta,
        )
        logger.info("AD-451: ValidationFramework wired (ReconciliationEscalator)")
```

> Verify-first: `runtime.red_team_agents` is the public attribute (post-AD-455 promotion verified at `runtime.py:246, 343`). `runtime.emit_event` is the post-AD-680 public method at `runtime.py:771`. `runtime.reconciliation_escalator` is published as a public attribute (no leading underscore) per the Wave 5 retrospective convention.

---

## Tests

**File:** `tests/test_ad451_validation_framework.py`

14 tests using `_FakeRedTeam` and `_FakeRuntime` stubs:

1. `test_event_type_validation_reconciliation_requested_exists`
2. `test_event_type_validation_outcome_verified_exists`
3. `test_config_defaults` — `ValidationFrameworkConfig()` defaults: `enabled=True`, `metadata_threshold=0.85`, `min_confidence_delta=0.20`.
4. `test_two_stage_verifier_metadata_only_path` — clean claimed result, no error → metadata-only outcome with `metadata_only=True`, `live_confidence=0.0`.
5. `test_two_stage_verifier_escalates_on_error` — claimed result has `error` → live verification invoked.
6. `test_two_stage_verifier_escalates_on_low_confidence` — metadata threshold 0.99 forces live path.
7. `test_two_stage_verifier_emits_outcome_event` — emit fires with `VALIDATION_OUTCOME_VERIFIED`.
8. `test_reconciliation_agreement_no_third_invoked` — both verifiers agree → `third_invoked=False`, `reason="agreement"`.
9. `test_reconciliation_confidence_delta_resolves` — confidence delta >= 0.20, disagreement → higher-confidence verdict picked, `reason="confidence_delta"`.
10. `test_reconciliation_majority_vote` — small confidence delta + 3+ red-team agents → third invoked, majority-vote chosen, `reason="majority_vote"`.
11. `test_reconciliation_third_unavailable` — small confidence delta + < 3 red-team agents → log-and-degrade, `reason="third_unavailable"`.
12. `test_reconciliation_emit_includes_chosen_verdict` — emit payload contains `chosen_verdict` boolean.
13. `test_self_verification_hook_protocol_shape` — `SelfVerificationHook` is a `Protocol`; a concrete implementation satisfies `isinstance` via duck typing.
14. `test_runtime_attribute_is_public` — after wiring, `runtime.reconciliation_escalator` exists (no underscore).

Boundary coverage: happy path + error/edge case + None-input (Tests 4–7 for TwoStageVerifier; 8–11 for Reconciliation).

---

## What This Does NOT Change

- `RedTeamAgent.verify()` API is unchanged. No new method on `RedTeamAgent`.
- Trust scores are not mutated. Reconciliation outcomes are diagnostic.
- `SelfVerificationHook` protocol is shipped but **not wired** into `CognitiveAgent.act()` — that wiring is deferred to AD-451b.
- `SystemQAAgent.run_smoke_tests()` is unchanged.
- Consensus voting weights and quorum thresholds are unchanged.
- No new agent pool. No middleware around `IntentBus`.

---

## Tracking

- `PROGRESS.md`: add `AD-451 CLOSED. Validation Framework Hardening — ...`
- `docs/development/roadmap.md`: flip AD-451 status from `*(planned, OSS)*` to `*(complete)*` near line 4117.
- `DECISIONS.md`: optional entry recording the deferred-AD-451b decision (SelfVerificationHook protocol shipped without wiring) — Builder discretion.

---

## Pre-Commit Sanity Check (HARD RULE)

```pwsh
git diff --cached --stat
```

If any tracker file shows >200 deletions, STOP. Tracker files are append-mostly.

Expected delta:
- `src/probos/cognitive/validation_framework.py`: ~280 lines (new).
- `src/probos/events.py`: 2 lines added.
- `src/probos/config.py`: ~10 lines added.
- `src/probos/startup/finalize.py`: ~14 lines added.
- `tests/test_ad451_validation_framework.py`: ~280 lines (new).
- `PROGRESS.md`, `roadmap.md`: ~3 lines changed.

---

## Acceptance Criteria

- All 14 tests pass under `pytest tests/test_ad451_validation_framework.py -v -n 0`.
- Full parallel gate `pytest tests/ -q -n 8 --dist=loadfile` is non-decreasing vs baseline.
- 2 new EventTypes appear exactly once in `events.py` at the documented insertion point.
- `runtime.reconciliation_escalator` is published as a public attribute (per Wave 5 retrospective convention).
- `RedTeamAgent.verify()` is read but never modified.
- AD-451's destructive-intent rule: `ReconciliationEscalator` only emits diagnostic events; consensus voting is unchanged. No `requires_consensus=True` introduction.
- Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.

---

## Verified Against Codebase (2026-05-01)

```
grep -n "async def verify" src/probos/agents/red_team.py
  66:    async def verify(

grep -n "class RedTeamAgent" src/probos/agents/red_team.py
  25: class RedTeamAgent(BaseAgent):

grep -n "class SystemQAAgent\|run_smoke_tests" src/probos/agents/system_qa.py
  69: class SystemQAAgent(BaseAgent):
  236:    async def run_smoke_tests(

grep -rn "ValidationFramework\|ReconciliationEscalator\|TwoStageVerifier\|SelfVerificationHook" src/probos/
  (no matches — AD-451 introduces these names)

grep -rn "VALIDATION_RECONCILIATION\|VALIDATION_OUTCOME" src/probos/events.py
  (no matches — names are free)

grep -n "AGENT_SELF_NAMED" src/probos/events.py
  190:    AGENT_SELF_NAMED = "agent_self_named"  # AD-499

grep -n "orders: OrdersConfig" src/probos/config.py
  (added in AD-440 — Section 5 SEARCH anchor)

grep -n "red_team_agents" src/probos/runtime.py
  246:    red_team_agents: list[RedTeamAgent]
  343:        self.red_team_agents: list[RedTeamAgent] = []
  (post-AD-455 public attribute — verified)

grep -n "def emit_event" src/probos/runtime.py
  771:    def emit_event(self, event: BaseEvent | EventType | str, ...
```
