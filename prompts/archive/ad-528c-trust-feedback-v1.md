# AD-528c v1 — Ground-Truth Verification: Trust-Network Feedback

**Status:** ready
**Dependencies:** AD-528 v1 (`GroundTruthVerifier`, `GroundTruthResult`, `EventType.VERIFICATION_PASSED` / `VERIFICATION_FAILED` — shipped Wave 7); AD-528b v1 (`GroundTruthRejectionGate`, `RejectionDecision`, `EventType.VERIFICATION_REJECTED` / `WORK_ITEM_QUARANTINED` — shipped Wave 58); AD-680 (`runtime.emit_event` + `runtime.add_event_listener` public — shipped); existing `TrustNetwork.record_outcome(agent_id, success, weight, intent_type, episode_id, verifier_id, source)` public API (`consensus/trust.py:208-216`); AD-558 trust-cascade dampening (applied internally by `record_outcome` — no AD-528c coupling)
**Estimated tests:** 12 new (1 new test file `tests/test_ad528c_trust_feedback.py`)
**Closes:** GH issue #402

---

## Problem

`GroundTruthVerifier` (AD-528 v1, `cognitive/ground_truth.py`) emits `VERIFICATION_PASSED` / `VERIFICATION_FAILED`. `GroundTruthRejectionGate` (AD-528b v1, same module) emits `VERIFICATION_REJECTED` / `WORK_ITEM_QUARANTINED`. Neither AD touches `runtime.trust_network`. AD-528b's class docstring contracts the boundary explicitly (`ground_truth.py:299-300`):

```
"""Trust-network feedback (raise/lower trust on PASSED/FAILED/REJECTED)
is a distinct AD — AD-528c (Wave 59). v1 of this class has zero
coupling to ``runtime.trust_network`` or ``probos.consensus.trust``.
"""
```

GH issue #402:

> "Feed verification outcomes back into TrustNetwork via `record_outcome()`. Discrepancy between agent claim and verification adjusts trust scores. v1 intentionally kept trust scoring out of the loop during system stabilization."

The roadmap entry (`docs/development/roadmap.md:6515`):

> "AD-528c: Ground-Truth Verification — Trust-Network Feedback *(Scoped, OSS, Issue #402)* — Feed verification outcomes back into TrustNetwork. Discrepancy between agent claim and verification reduces trust score; matched claims raise it. Connects to AD-528 (verification layer) + AD-558 (cascade dampening)."

AD-528c v1 closes the learning-loop gap. It is a pure event-listener + sidecar — no modification of `GroundTruthVerifier`, `GroundTruthRejectionGate`, `TrustNetwork`, or `consensus/trust.py`. It subscribes to verification events via the existing `runtime.add_event_listener(fn, event_types=...)` API and calls the existing public `runtime.trust_network.record_outcome(agent_id, success, weight, intent_type, episode_id, verifier_id, source)` API.

**ProbOS principle 3 compliance is structural.** `record_outcome` internally stores raw `(alpha, beta)` Beta-distribution parameters (`consensus/trust.py:42-43`, `consensus/trust.py:306-308` — `record.alpha += effective_weight` / `record.beta += effective_weight`) and persists them raw to SQLite (`consensus/trust.py:553-555` — `INSERT INTO trust_scores (agent_id, alpha, beta, updated)`). AD-528c v1 invokes only the public method — it does NOT bypass the contract by writing derived `score = alpha/(alpha+beta)` values, does NOT skip AD-558 dampening (which `record_outcome` applies internally), and does NOT touch `record.alpha` / `record.beta` directly.
This AD plumbs the seam:

```
GroundTruthVerifier (AD-528 v1 — UNCHANGED)
    └── verify(...) → GroundTruthResult
            └── _emit() → runtime.emit_event(VERIFICATION_PASSED | VERIFICATION_FAILED, {...})

GroundTruthRejectionGate (AD-528b v1 — UNCHANGED)
    └── evaluate(...) → RejectionDecision
            └── (calls verifier.verify() internally, which fires PASSED/FAILED unconditionally)
            └── _emit() → runtime.emit_event(VERIFICATION_REJECTED | WORK_ITEM_QUARANTINED, {...})

GroundTruthTrustFeedback (NEW)
    └── on_event(event: dict) → None        # registered via runtime.add_event_listener
            ├── reads event["type"] + event["data"]
            ├── if type == VERIFICATION_PASSED.value: record_outcome(agent_id, success=True,  weight=success_weight)
            ├── if type == VERIFICATION_FAILED.value: record_outcome(agent_id, success=False, weight=failure_weight)
            └── else (REJECTED, QUARANTINED, anything): no-op   # double-counting prevention; see Solution

TrustNetwork (UNCHANGED)
    └── record_outcome(agent_id, success, weight, ...) → float
            ├── applies AD-558 dampening + cascade breaker + hard floor
            ├── mutates record.alpha (success) or record.beta (failure)
            └── persists raw (alpha, beta) — ProbOS principle 3 compliance is internal

startup/finalize.py wiring (NEW sub-block inside existing AD-528 if-block, AFTER AD-528b sub-block)
    if config.ground_truth.trust_feedback_enabled and runtime.trust_network is not None:
        feedback = GroundTruthTrustFeedback(runtime=runtime, success_weight=..., failure_weight=...)
        runtime.add_event_listener(feedback.on_event, event_types=[
            EventType.VERIFICATION_PASSED.value,
            EventType.VERIFICATION_FAILED.value,
        ])
        runtime.ground_truth_trust_feedback = feedback
    else:
        runtime.ground_truth_trust_feedback = None
```

`v1 ships the layer + finalize wiring + tests.` AD-528c is DIFFERENT from AD-528 / AD-528b in that the listener IS the consumer integration — there's no separate "AD-528c-2 caller integration" deferral. The moment AD-528 finalize wiring landed (Wave 7), `runtime.emit_event(VERIFICATION_PASSED, ...)` and `runtime.emit_event(VERIFICATION_FAILED, ...)` started firing whenever something calls `verifier.verify()`. AD-528c v1 simply subscribes. The catch: AD-528 has zero production callers of `verify()` either, so in practice no events fire today. AD-528c v1 ships the listener + wiring + 12 unit tests; the listener becomes observably active once AD-528b-2 (caller integration of the rejection gate, deferred from Wave 58) lands. Until then: feedback is a no-op in production but fully unit-tested.

The default-flip of `trust_feedback_enabled`, REJECTED-aware weighting, Counselor / Captain alert routing on trust-floor hits triggered by ground-truth feedback, AD-558 cascade-breaker integration audit, HXI dashboard surface, and commercial overlays are deferred to AD-528c-1 / -2 / -3 / -4 / -5 / -6 *(Commercial)* respectively.

## Solution

v1 ships:

1. **`GroundTruthTrustFeedback`** — new module-level class in `cognitive/ground_truth.py`, defined AFTER `GroundTruthRejectionGate`. Constructor: `__init__(self, *, runtime: Any, success_weight: float = 1.0, failure_weight: float = 0.5) -> None`. Public method: sync `on_event(event: dict[str, Any]) -> None` — the listener callback registered via `runtime.add_event_listener`.

2. **Listener semantics (v1)** — consumes `VERIFICATION_PASSED` and `VERIFICATION_FAILED` only. `VERIFICATION_REJECTED` is **NOT** consumed in v1: every REJECTED co-fires with a FAILED inside `verifier.verify()` (`ground_truth.py:163-181` — the verifier's `_emit` fires PASSED/FAILED unconditionally, before `GroundTruthRejectionGate.evaluate`'s own emit logic runs at `ground_truth.py:282-322`). If AD-528c v1 listened to all three event types, every rejection-gate-driven failure would update `record_outcome(success=False)` TWICE — once on FAILED and once on REJECTED. Distinct REJECTED-aware weighting (escalate negative weight when the gate engaged) is deferred to AD-528c-1.

3. **Outcome mapping** — `PASSED → record_outcome(success=True, weight=success_weight)`; `FAILED → record_outcome(success=False, weight=failure_weight)`. Default weights: success=1.0 (full positive update), failure=0.5 (partial negative update). Asymmetric defaults reflect that "verifier scored low" is a softer signal than "outcome confirmed" — AD-558's progressive dampening + cascade breaker + hard floor (applied internally by `record_outcome`) provide additional safety on top.

4. **`record_outcome` kwargs locked** — `intent_type="ground_truth_verification"`, `episode_id=str(data.get("booking_id", ""))`, `verifier_id="ground_truth"`, `source="ground_truth_verification"`. These kwargs distinguish ground-truth-driven trust updates from existing consensus-driven updates (`runtime.py:1995-2008` uses `source="verification"` default).

5. **`GroundTruthConfig.trust_feedback_enabled: bool = False`** — Convention #14 + #3 + Wave 55-58 sibling pattern: default False on the transitional flag. AD-528c-1 flips default True after fleet rehearsal.

6. **`GroundTruthConfig.trust_feedback_success_weight: float = Field(default=1.0, ge=0.0)`** — operator-tunable success update magnitude.

7. **`GroundTruthConfig.trust_feedback_failure_weight: float = Field(default=0.5, ge=0.0)`** — operator-tunable failure update magnitude.

8. **`startup/finalize.py` wiring** — single new sub-block inserted INSIDE the existing AD-528 `if config.ground_truth.enabled:` block, AFTER the AD-528b rejection-gate sub-block (`finalize.py:1390-1410`) and BEFORE the closing `logger.info("AD-528: ...")` line (`finalize.py:1411-1415`). Constructs `GroundTruthTrustFeedback` only when `config.ground_truth.trust_feedback_enabled and runtime.trust_network is not None`. Registers the listener via `runtime.add_event_listener(feedback.on_event, event_types=[VERIFICATION_PASSED.value, VERIFICATION_FAILED.value])`. Sets `runtime.ground_truth_trust_feedback = feedback` (greenfield runtime attribute). The OUTER else-branch (`finalize.py:1416-1419`) extends to set `runtime.ground_truth_trust_feedback = None`.

9. **No new EventType.** v1 reuses existing `VERIFICATION_PASSED` and `VERIFICATION_FAILED`. No `events.py` modification.

`Backwards compatibility`: every existing AD-528 test (`test_ad528_ground_truth.py` — 14 tests) and AD-528b test (`test_ad528b_active_rejection.py` — 14 tests) continues to function. No symbol is removed; no signature is changed; verifier, episode writer, rejection gate, and rejection decision are NOT modified. New `GroundTruthTrustFeedback` is greenfield; new `trust_feedback_enabled` defaults False; new weight fields default to sensible values. Existing constructions of `GroundTruthVerifier(...)`, `VerificationEpisodeWriter(...)`, `GroundTruthRejectionGate(...)`, and `TrustNetwork.record_outcome(...)` behave identically to today.

### Scope

| Component | Status |
|---|---|
| `GroundTruthTrustFeedback` class (init, on_event) | NEW (module-level in `cognitive/ground_truth.py`) |
| `GroundTruthConfig.trust_feedback_enabled` | NEW |
| `GroundTruthConfig.trust_feedback_success_weight` | NEW |
| `GroundTruthConfig.trust_feedback_failure_weight` | NEW |
| `startup/finalize.py` trust-feedback wiring (sub-block + else-branch extension) | EDIT (additive) |
| `runtime.ground_truth_trust_feedback` attribute (greenfield) | NEW (set in finalize) |
| `tests/test_ad528c_trust_feedback.py` (12 tests) | NEW |

### Out of scope (legitimate boundaries — DO NOT BUILD)

- **Default-flip of `trust_feedback_enabled` to True.** Convention #14 + Convention #3. Deferred to AD-528c-1 once a fleet-wide rehearsal confirms no false-positive trust drops under real workload.
- **REJECTED-aware weighting** (escalate negative weight when the rejection gate engaged — e.g. PASSED=+1.0, FAILED=-0.5, REJECTED=-1.0 stacked or REJECTED replaces FAILED to avoid double-counting). v1 emits NO trust update for REJECTED to avoid double-counting (every REJECTED co-fires with FAILED). Deferred to AD-528c-1 (combine with default-flip — same wave will determine the policy).
- **Counselor / Captain alert routing on ground-truth-driven trust-floor hits.** AD-558 already emits `TRUST_CASCADE_WARNING`; AD-528c does not add a new alert surface. Future polish: tag trust-cascade events with their source so HXI can surface "trust drop attributed to ground-truth verification". Deferred to AD-528c-2.
- **AD-558 cascade-breaker integration audit.** v1 invokes `record_outcome` and inherits cascade dampening for free (the dampening is applied by `record_outcome` regardless of caller). An explicit audit — verify that ground-truth feedback respects existing dampening + floor + cascade across realistic event volumes — is deferred to AD-528c-3 (load-test-style integration).
- **HXI dashboard surface for "trust impact attributed to ground-truth verification".** v1 does not expose the per-feedback statistics through any UI surface. The data is observable via `TrustNetwork.event_log` (the existing AD-558 ring buffer at `consensus/trust.py:309-323` already records `intent_type=ground_truth_verification` for these calls). HXI/REST surfacing is AD-528c-4 territory.
- **Re-aggregation / re-scoring on retraction.** If a rejection is later reversed (re-verification succeeds, agent re-submits evidence), v1 does NOT roll back the trust beta increment. Trust is monotonically additive; recovery happens via subsequent successful outcomes. Future polish (transactional trust updates with rollback) is AD-528c-5.
- **Commercial overlays** — *compliance-grade trust attribution / per-jurisdiction trust-update audit trails / GDPR-compliant trust-data export hooks / regulator-facing trust-evidence chain*. *(Commercial)* — extension point only; v1's `runtime.ground_truth_trust_feedback` attribute + `TrustNetwork.event_log` ring buffer IS the plug-in seam where commercial overlays attach. Deferred to AD-528c-6.
- **No new pool, agent, or module beyond the 1 new test file.** No new EventType. No new Pydantic config class — fields append to existing `GroundTruthConfig`. No new file beyond `tests/test_ad528c_trust_feedback.py`.
- **No modification of `GroundTruthVerifier`.** Existing 11 verifier tests continue to pass.
- **No modification of `GroundTruthRejectionGate`.** Existing 14 AD-528b tests continue to pass.
- **No modification of `VerificationEpisodeWriter`.** Existing 3 episode-writer tests continue to pass.
- **No modification of `TrustNetwork` / `consensus/trust.py` / `TrustRecord`.** AD-528c v1 invokes the existing public `record_outcome` API only.
- **No subscription to `VERIFICATION_REJECTED` or `WORK_ITEM_QUARANTINED`.** Co-firing semantics + double-counting concern. Deferred to AD-528c-1.
- **No raw `(alpha, beta)` mutation.** ProbOS principle 3 — invoke `record_outcome` only; do NOT mutate `record.alpha` / `record.beta` directly; do NOT skip dampening; do NOT manipulate `_dampening` / `_cascade` / `_records`.

---

## Verified Against Codebase (HEAD post-Wave-58, `6b24d75`, 2026-05-05)

| Symbol | Path | Line | Verifying line |
|---|---|---|---|
| `GroundTruthRejectionGate` class (insertion-anchor sibling — new code goes AFTER) | `src/probos/cognitive/ground_truth.py` | 278 | `class GroundTruthRejectionGate:` |
| `GroundTruthRejectionGate._emit` final body (insertion target — last lines of class at HEAD) | `src/probos/cognitive/ground_truth.py` | ~436-442 | `try: self._emit_event(event_type, payload) ... except Exception: logger.warning("AD-528b: %s emit failed", event_type.value, exc_info=True,)` |
| `GroundTruthVerifier._emit` (existing emit shape, sibling reference) | `src/probos/cognitive/ground_truth.py` | 163-181 | `def _emit(self, result: GroundTruthResult) -> None: ... self._emit_event(et, ...)` (fires PASSED/FAILED unconditionally per result.verified) |
| AD-528b boundary docstring (the contract this AD closes) | `src/probos/cognitive/ground_truth.py` | 298-299 | `Trust-network feedback (raise/lower trust on PASSED/FAILED/REJECTED) is a distinct AD — AD-528c (Wave 59). v1 of this class has zero coupling to ``runtime.trust_network`` or ``probos.consensus.trust``.` |
| `from __future__ import annotations` (already present — enables forward refs) | `src/probos/cognitive/ground_truth.py` | 9 | `from __future__ import annotations` |
| Existing imports (`logging`, `time`, `dataclass`/`field`, `TYPE_CHECKING`, `Any`, `EventType`) | `src/probos/cognitive/ground_truth.py` | 11-16 | `import logging` … `import time` … `from dataclasses import dataclass, field` … `from typing import TYPE_CHECKING, Any` … `from probos.events import EventType` |
| `EventType.VERIFICATION_PASSED` (consumed) | `src/probos/events.py` | 215 | `VERIFICATION_PASSED = "verification_passed"  # AD-528` |
| `EventType.VERIFICATION_FAILED` (consumed) | `src/probos/events.py` | 216 | `VERIFICATION_FAILED = "verification_failed"  # AD-528` |
| `GroundTruthConfig` Pydantic class | `src/probos/config.py` | 1292 | `class GroundTruthConfig(BaseModel):` |
| `GroundTruthConfig` existing 6 fields + AD-528b comment block | `src/probos/config.py` | 1295-1308 | `enabled: bool = True` … `threshold: float = Field(default=0.75, ge=0.0, le=1.0)` … `event_window_seconds: float = Field(default=600.0, ge=10.0)` … `write_episode: bool = True` … (AD-528b comment block) … `active_rejection_enabled: bool = False` … `quarantine_metadata_key: str = "ground_truth_quarantine"` |
| `OperationsConfig` (sibling — class after `GroundTruthConfig`, used as REPLACE re-emit anchor) | `src/probos/config.py` | 1311 | `class OperationsConfig(BaseModel):` |
| AD-528 finalize block — full body including AD-528b sub-block + outer else | `src/probos/startup/finalize.py` | 1371-1419 | `# AD-528: Ground-Truth Task Verification (v1: read-only scoring + emit).` … `# AD-528b: optional active-rejection gate (default disabled).` … `if config.ground_truth.enabled:` … `runtime.ground_truth_verifier = GroundTruthVerifier(...)` … (AD-528b sub-block) … `else: runtime.ground_truth_rejection_gate = None` … `logger.info("AD-528: GroundTruthVerifier wired ...")` … `else: runtime.ground_truth_verifier = None ; runtime.verification_episode_writer = None ; runtime.ground_truth_rejection_gate = None` |
| `runtime.add_event_listener` signature | `src/probos/runtime.py` | 683-687 | `def add_event_listener(self, fn: Callable[..., Any], event_types: Iterable[str] \| None = None,) -> None:` |
| `runtime.trust_network` attribute init | `src/probos/runtime.py` | 335 | `self.trust_network = TrustNetwork(...)` |
| `TrustNetwork.record_outcome` signature | `src/probos/consensus/trust.py` | 208-217 | `def record_outcome(self, agent_id: AgentID, success: bool, weight: float = 1.0, intent_type: str = "", episode_id: str = "", verifier_id: str = "", source: str = "verification",) -> float:` |
| `TrustRecord` raw `(alpha, beta)` storage (ProbOS principle 3) | `src/probos/consensus/trust.py` | 42-43 | `alpha: float = 2.0  # Prior + successes` / `beta: float = 2.0  # Prior + failures` |
| `record_outcome` raw mutation (proves ProbOS principle 3 compliance is internal) | `src/probos/consensus/trust.py` | 306-308 | `if success: record.alpha += effective_weight else: record.beta += effective_weight` |
| Event payload shape from `runtime._emit_event` (consumed by listener) | `src/probos/runtime.py` | 786-790 | `event = {"type": event_type.value, "data": data or {}, "timestamp": time.time()}` |
| `_emit_event_local` listener dispatch (proves sync vs async routing) | `src/probos/runtime.py` | 805-815 | `for fn, type_filter in self._event_listeners: ... if asyncio.iscoroutinefunction(fn): asyncio.create_task(fn(event)) else: fn(event)` |
| Existing AD-528 tests (no modification) | `tests/test_ad528_ground_truth.py` | 73-263 | 14 tests pass at HEAD |
| Existing AD-528b tests (no modification) | `tests/test_ad528b_active_rejection.py` | (full file) | 14 tests pass at HEAD |

`GroundTruthTrustFeedback`, `GroundTruthTrustFeedback.on_event`, `GroundTruthConfig.trust_feedback_enabled`, `GroundTruthConfig.trust_feedback_success_weight`, `GroundTruthConfig.trust_feedback_failure_weight`, `runtime.ground_truth_trust_feedback`, `tests/test_ad528c_trust_feedback.py` — all greenfield, verified zero hits at HEAD `6b24d75`.

`AD-528a` artifact verification — zero hits in `prompts/`, `prompts/archive/`, `DECISIONS.md`, `decisions-era-*.md`, `PROGRESS.md`, `progress-era-*.md`, `docs/development/roadmap.md` at HEAD `6b24d75`. AD-528c is the c-tier root with no prior `a` sibling.

---

## Implementation

### Section 1 — Config Fields

**File:** `src/probos/config.py`

`SEARCH` block (the `GroundTruthConfig` body plus the immediately-following blank line and `OperationsConfig` head, lines 1292-1311):
```python
class GroundTruthConfig(BaseModel):
    """Ground-truth task verification configuration (AD-528, AD-528b)."""

    enabled: bool = True
    threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    event_window_seconds: float = Field(default=600.0, ge=10.0)
    write_episode: bool = True
    # AD-528b: active rejection & metadata quarantine. Default False per
    # Convention #14 (transitional flag) + Convention #3 (default off until
    # caller integration lands at AD-528b-2). When True, finalize.py
    # constructs a GroundTruthRejectionGate that wraps the verifier; the
    # gate emits VERIFICATION_REJECTED + WORK_ITEM_QUARANTINED on the
    # rejection branch and writes a quarantine payload into the work item's
    # metadata under `quarantine_metadata_key`.
    active_rejection_enabled: bool = False
    quarantine_metadata_key: str = "ground_truth_quarantine"


class OperationsConfig(BaseModel):
```

`REPLACE`:
```python
class GroundTruthConfig(BaseModel):
    """Ground-truth task verification configuration (AD-528, AD-528b, AD-528c)."""

    enabled: bool = True
    threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    event_window_seconds: float = Field(default=600.0, ge=10.0)
    write_episode: bool = True
    # AD-528b: active rejection & metadata quarantine. Default False per
    # Convention #14 (transitional flag) + Convention #3 (default off until
    # caller integration lands at AD-528b-2). When True, finalize.py
    # constructs a GroundTruthRejectionGate that wraps the verifier; the
    # gate emits VERIFICATION_REJECTED + WORK_ITEM_QUARANTINED on the
    # rejection branch and writes a quarantine payload into the work item's
    # metadata under `quarantine_metadata_key`.
    active_rejection_enabled: bool = False
    quarantine_metadata_key: str = "ground_truth_quarantine"
    # AD-528c: trust-network feedback. Default False per Convention #14
    # (transitional flag) + Convention #3 (default off until fleet rehearsal
    # confirms no false-positive trust drops, AD-528c-1). When True,
    # finalize.py registers a GroundTruthTrustFeedback listener that
    # subscribes to VERIFICATION_PASSED + VERIFICATION_FAILED and calls
    # runtime.trust_network.record_outcome(...) — the public API that
    # internally stores raw (alpha, beta) per ProbOS principle 3.
    # VERIFICATION_REJECTED is NOT consumed in v1 (every REJECTED co-fires
    # with FAILED inside verifier.verify(); double-counting prevention).
    # REJECTED-aware weighting is deferred to AD-528c-1.
    trust_feedback_enabled: bool = False
    trust_feedback_success_weight: float = Field(default=1.0, ge=0.0)
    trust_feedback_failure_weight: float = Field(default=0.5, ge=0.0)


class OperationsConfig(BaseModel):
```

### Section 2 — `cognitive/ground_truth.py` extensions

**File:** `src/probos/cognitive/ground_truth.py`

`SEARCH` block (the trailing lines of `GroundTruthRejectionGate._emit`, anchored on the file's final `logger.warning(... exc_info=True,)` close paren):
```python
    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        """Synchronously emit an event via the optional ``emit_event`` hook.

        Mirrors ``GroundTruthVerifier._emit`` shape. If no hook is set, the
        emit is silent (no-op) — the gate's behaviour (decision + metadata
        apply) still executes. If the hook raises, the exception is logged
        and swallowed (tier-2 log-and-degrade) so a downstream consumer's
        bug cannot break the rejection-decision path.
        """
        if not self._emit_event:
            return
        try:
            self._emit_event(event_type, payload)
        except Exception:
            logger.warning(
                "AD-528b: %s emit failed", event_type.value, exc_info=True,
            )
```

`REPLACE`:
```python
    def _emit(self, event_type: EventType, payload: dict[str, Any]) -> None:
        """Synchronously emit an event via the optional ``emit_event`` hook.

        Mirrors ``GroundTruthVerifier._emit`` shape. If no hook is set, the
        emit is silent (no-op) — the gate's behaviour (decision + metadata
        apply) still executes. If the hook raises, the exception is logged
        and swallowed (tier-2 log-and-degrade) so a downstream consumer's
        bug cannot break the rejection-decision path.
        """
        if not self._emit_event:
            return
        try:
            self._emit_event(event_type, payload)
        except Exception:
            logger.warning(
                "AD-528b: %s emit failed", event_type.value, exc_info=True,
            )


# ---------------------------------------------------------------------------
# AD-528c: Trust-Network Feedback
# ---------------------------------------------------------------------------


class GroundTruthTrustFeedback:
    """Subscribes to ground-truth verification events; updates ``TrustNetwork``.

    v1 surface: registered as a sync listener via
    ``runtime.add_event_listener(feedback.on_event, event_types=[
        EventType.VERIFICATION_PASSED.value,
        EventType.VERIFICATION_FAILED.value,
    ])`` in ``startup/finalize.py``. On each event, ``on_event`` reads the
    event payload, extracts ``agent_id`` + ``booking_id``, and calls
    ``runtime.trust_network.record_outcome(...)`` with an asymmetric weight
    scheme: ``success_weight`` (default 1.0) on PASSED, ``failure_weight``
    (default 0.5) on FAILED.

    ``VERIFICATION_REJECTED`` and ``WORK_ITEM_QUARANTINED`` are NOT consumed
    in v1. Every REJECTED co-fires with a FAILED inside
    ``GroundTruthVerifier._emit`` (the verifier emits PASSED/FAILED
    unconditionally before the rejection-gate emit logic runs). Listening
    to REJECTED would double-count negative trust updates. Distinct
    REJECTED-aware weighting (escalate negative weight when the gate
    engaged) is deferred to AD-528c-1.

    ProbOS principle 3 compliance is structural — ``record_outcome``
    internally stores raw ``(alpha, beta)`` Beta-distribution parameters
    and applies AD-558 dampening + cascade breaker + hard floor. v1
    invokes the public method only; never mutates ``record.alpha`` /
    ``record.beta`` directly, never bypasses dampening, never derives
    means.

    Tier-2 log-and-degrade: a ``record_outcome`` exception is logged at
    WARNING with ``exc_info=True`` but NOT propagated — the listener is
    invoked from ``runtime._emit_event_local`` which already wraps in
    debug-level swallowing; the inner WARNING gives operators a visible
    failure signal without crashing the event-dispatch path.
    """

    def __init__(
        self,
        *,
        runtime: Any,
        success_weight: float = 1.0,
        failure_weight: float = 0.5,
    ) -> None:
        self._runtime = runtime
        self._success_weight = success_weight
        self._failure_weight = failure_weight

    def on_event(self, event: dict[str, Any]) -> None:
        """Process a single verification event; update trust if applicable.

        Synchronous (not ``async``) — the runtime's ``_emit_event_local``
        routes sync vs async via ``asyncio.iscoroutinefunction``; sync is
        preferred because ``record_outcome`` itself is sync and we avoid
        spawning fire-and-forget tasks per event.
        """
        type_str = event.get("type", "")
        data = event.get("data", {}) or {}
        agent_id = str(data.get("agent_id", ""))
        if not agent_id:
            return
        tn = getattr(self._runtime, "trust_network", None)
        if tn is None:
            return
        if type_str == EventType.VERIFICATION_PASSED.value:
            success, weight = True, self._success_weight
        elif type_str == EventType.VERIFICATION_FAILED.value:
            success, weight = False, self._failure_weight
        else:
            # REJECTED, QUARANTINED, and any future event type: no-op in v1.
            # See class docstring for double-counting rationale.
            return
        booking_id = str(data.get("booking_id", ""))
        try:
            tn.record_outcome(
                agent_id,
                success=success,
                weight=weight,
                intent_type="ground_truth_verification",
                episode_id=booking_id,
                verifier_id="ground_truth",
                source="ground_truth_verification",
            )
        except Exception:
            logger.warning(
                "AD-528c: trust_network.record_outcome failed (agent_id=%s, success=%s)",
                agent_id, success, exc_info=True,
            )
```

### Section 3 — Finalize Wiring

**File:** `src/probos/startup/finalize.py`

`SEARCH` block (the existing AD-528 if-block including the AD-528b sub-block, the closing `logger.info("AD-528: ...")`, and the OUTER else-branch — `finalize.py:1371-1419`):
```python
    # AD-528: Ground-Truth Task Verification (v1: read-only scoring + emit).
    # AD-528b: optional active-rejection gate (default disabled).
    if config.ground_truth.enabled:
        from probos.cognitive.ground_truth import (
            GroundTruthVerifier,
            VerificationEpisodeWriter,
        )
        runtime.ground_truth_verifier = GroundTruthVerifier(
            runtime=runtime,
            emit_event=runtime.emit_event,
            threshold=config.ground_truth.threshold,
            event_window_seconds=config.ground_truth.event_window_seconds,
        )
        if config.ground_truth.write_episode:
            runtime.verification_episode_writer = VerificationEpisodeWriter(
                runtime=runtime,
            )
        else:
            runtime.verification_episode_writer = None
        # AD-528b: rejection gate wraps the verifier when the transitional
        # flag is set. Caller integration (consult gate before allowing
        # `→ done` transitions) is deferred to AD-528b-2; v1 ships the
        # layer + finalize wiring + tests with no production callers.
        if (
            config.ground_truth.active_rejection_enabled
            and runtime.ground_truth_verifier is not None
        ):
            from probos.cognitive.ground_truth import GroundTruthRejectionGate
            runtime.ground_truth_rejection_gate = GroundTruthRejectionGate(
                verifier=runtime.ground_truth_verifier,
                runtime=runtime,
                emit_event=runtime.emit_event,
                metadata_key=config.ground_truth.quarantine_metadata_key,
            )
            logger.info(
                "AD-528b: GroundTruthRejectionGate wired (metadata_key=%s)",
                config.ground_truth.quarantine_metadata_key,
            )
        else:
            runtime.ground_truth_rejection_gate = None
        logger.info(
            "AD-528: GroundTruthVerifier wired (threshold=%.2f, window=%.0fs)",
            config.ground_truth.threshold,
            config.ground_truth.event_window_seconds,
        )
    else:
        runtime.ground_truth_verifier = None
        runtime.verification_episode_writer = None
        runtime.ground_truth_rejection_gate = None
```

`REPLACE`:
```python
    # AD-528: Ground-Truth Task Verification (v1: read-only scoring + emit).
    # AD-528b: optional active-rejection gate (default disabled).
    # AD-528c: optional trust-network feedback listener (default disabled).
    if config.ground_truth.enabled:
        from probos.cognitive.ground_truth import (
            GroundTruthVerifier,
            VerificationEpisodeWriter,
        )
        runtime.ground_truth_verifier = GroundTruthVerifier(
            runtime=runtime,
            emit_event=runtime.emit_event,
            threshold=config.ground_truth.threshold,
            event_window_seconds=config.ground_truth.event_window_seconds,
        )
        if config.ground_truth.write_episode:
            runtime.verification_episode_writer = VerificationEpisodeWriter(
                runtime=runtime,
            )
        else:
            runtime.verification_episode_writer = None
        # AD-528b: rejection gate wraps the verifier when the transitional
        # flag is set. Caller integration (consult gate before allowing
        # `→ done` transitions) is deferred to AD-528b-2; v1 ships the
        # layer + finalize wiring + tests with no production callers.
        if (
            config.ground_truth.active_rejection_enabled
            and runtime.ground_truth_verifier is not None
        ):
            from probos.cognitive.ground_truth import GroundTruthRejectionGate
            runtime.ground_truth_rejection_gate = GroundTruthRejectionGate(
                verifier=runtime.ground_truth_verifier,
                runtime=runtime,
                emit_event=runtime.emit_event,
                metadata_key=config.ground_truth.quarantine_metadata_key,
            )
            logger.info(
                "AD-528b: GroundTruthRejectionGate wired (metadata_key=%s)",
                config.ground_truth.quarantine_metadata_key,
            )
        else:
            runtime.ground_truth_rejection_gate = None
        # AD-528c: trust-network feedback listener subscribes to
        # VERIFICATION_PASSED + VERIFICATION_FAILED and calls
        # runtime.trust_network.record_outcome(...). Default disabled per
        # Convention #14 + #3; AD-528c-1 flips default True after fleet
        # rehearsal. v1 has zero coupling to the rejection gate -- the
        # listener consumes existing AD-528 events directly.
        if (
            config.ground_truth.trust_feedback_enabled
            and runtime.trust_network is not None
        ):
            from probos.cognitive.ground_truth import GroundTruthTrustFeedback
            from probos.events import EventType
            feedback = GroundTruthTrustFeedback(
                runtime=runtime,
                success_weight=config.ground_truth.trust_feedback_success_weight,
                failure_weight=config.ground_truth.trust_feedback_failure_weight,
            )
            runtime.add_event_listener(
                feedback.on_event,
                event_types=[
                    EventType.VERIFICATION_PASSED.value,
                    EventType.VERIFICATION_FAILED.value,
                ],
            )
            runtime.ground_truth_trust_feedback = feedback
            logger.info(
                "AD-528c: GroundTruthTrustFeedback wired (success_weight=%.2f, failure_weight=%.2f)",
                config.ground_truth.trust_feedback_success_weight,
                config.ground_truth.trust_feedback_failure_weight,
            )
        else:
            runtime.ground_truth_trust_feedback = None
        logger.info(
            "AD-528: GroundTruthVerifier wired (threshold=%.2f, window=%.0fs)",
            config.ground_truth.threshold,
            config.ground_truth.event_window_seconds,
        )
    else:
        runtime.ground_truth_verifier = None
        runtime.verification_episode_writer = None
        runtime.ground_truth_rejection_gate = None
        runtime.ground_truth_trust_feedback = None
```

### Section 4 — Tests

**File:** `tests/test_ad528c_trust_feedback.py` (NEW)

Full test file:

```python
"""AD-528c: Ground-Truth Trust-Network Feedback tests.

Subscribes to AD-528 verification events (PASSED/FAILED) and updates
TrustNetwork via the public record_outcome API. v1 invokes the public
method only — ProbOS principle 3 (raw alpha/beta storage) is enforced
by TrustNetwork internally; AD-528c never bypasses it.

VERIFICATION_REJECTED is NOT consumed in v1 (co-fires with FAILED;
double-counting prevention). Distinct REJECTED-aware weighting is
deferred to AD-528c-1.
"""

from __future__ import annotations

import inspect
import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from probos.cognitive.ground_truth import GroundTruthTrustFeedback
from probos.config import GroundTruthConfig
from probos.events import EventType


# ----- Helpers -----


def _make_runtime(*, with_trust_network: bool = True):
    """Build a SimpleNamespace runtime with optional MagicMock trust_network."""
    rt = SimpleNamespace()
    if with_trust_network:
        rt.trust_network = MagicMock()
        rt.trust_network.record_outcome = MagicMock(return_value=0.5)
    else:
        rt.trust_network = None
    return rt


def _make_feedback(rt=None, **kwargs):
    if rt is None:
        rt = _make_runtime()
    fb = GroundTruthTrustFeedback(runtime=rt, **kwargs)
    return fb, rt


def _evt(type_str: str, **data) -> dict:
    """Build an event payload matching runtime._emit_event shape."""
    return {"type": type_str, "data": data, "timestamp": 0.0}


# ----- 1-3: Config field defaults -----


def test_ground_truth_config_trust_feedback_enabled_default_false():
    cfg = GroundTruthConfig()
    assert cfg.trust_feedback_enabled is False


def test_ground_truth_config_trust_feedback_success_weight_default():
    cfg = GroundTruthConfig()
    assert cfg.trust_feedback_success_weight == 1.0


def test_ground_truth_config_trust_feedback_failure_weight_default():
    cfg = GroundTruthConfig()
    assert cfg.trust_feedback_failure_weight == 0.5


# ----- 4: PASSED dispatch -----


def test_on_event_passed_calls_record_outcome_success_true():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, agent_id="a1", booking_id="bk1"))
    assert rt.trust_network.record_outcome.call_count == 1
    call = rt.trust_network.record_outcome.call_args
    assert call.args == ("a1",)
    assert call.kwargs["success"] is True
    assert call.kwargs["weight"] == 1.0


# ----- 5: FAILED dispatch -----


def test_on_event_failed_calls_record_outcome_success_false():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.VERIFICATION_FAILED.value, agent_id="a1", booking_id="bk1"))
    assert rt.trust_network.record_outcome.call_count == 1
    call = rt.trust_network.record_outcome.call_args
    assert call.args == ("a1",)
    assert call.kwargs["success"] is False
    assert call.kwargs["weight"] == 0.5


# ----- 6-7: REJECTED + QUARANTINED no-op (double-counting prevention) -----


def test_on_event_rejected_is_noop():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.VERIFICATION_REJECTED.value, agent_id="a1", booking_id="bk1"))
    rt.trust_network.record_outcome.assert_not_called()


def test_on_event_quarantined_is_noop():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.WORK_ITEM_QUARANTINED.value, agent_id="a1", booking_id="bk1"))
    rt.trust_network.record_outcome.assert_not_called()


# ----- 8: Empty agent_id is a no-op -----



def test_on_event_empty_agent_id_is_noop():
    fb, rt = _make_feedback()
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, agent_id="", booking_id="bk1"))
    rt.trust_network.record_outcome.assert_not_called()
    # Missing agent_id key entirely
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, booking_id="bk1"))
    rt.trust_network.record_outcome.assert_not_called()


# ----- 9: Missing trust_network is a no-op -----


def test_on_event_missing_trust_network_is_noop():
    rt = _make_runtime(with_trust_network=False)
    fb = GroundTruthTrustFeedback(runtime=rt)
    # Should NOT raise
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, agent_id="a1", booking_id="bk1"))
    fb.on_event(_evt(EventType.VERIFICATION_FAILED.value, agent_id="a1", booking_id="bk1"))


# ----- 10: record_outcome exception swallowed (tier-2 log-and-degrade) -----


def test_on_event_record_outcome_exception_log_and_degrade(caplog):
    fb, rt = _make_feedback()
    rt.trust_network.record_outcome.side_effect = RuntimeError("trust db locked")
    with caplog.at_level(logging.WARNING):
        # Should NOT raise
        fb.on_event(_evt(EventType.VERIFICATION_FAILED.value, agent_id="a1", booking_id="bk1"))
    assert any(
        "AD-528c: trust_network.record_outcome failed" in rec.getMessage()
        for rec in caplog.records
    )


# ----- 11: on_event is sync, not async -----


def test_on_event_is_sync_not_async():
    fb, _rt = _make_feedback()
    assert inspect.iscoroutinefunction(fb.on_event) is False


# ----- 12: record_outcome kwargs locked -----


def test_on_event_passes_record_outcome_kwargs_correctly():
    fb, rt = _make_feedback(success_weight=3.5, failure_weight=0.75)
    fb.on_event(_evt(EventType.VERIFICATION_PASSED.value, agent_id="agent-7", booking_id="bk-x"))
    call = rt.trust_network.record_outcome.call_args
    assert call.args == ("agent-7",)
    assert call.kwargs == {
        "success": True,
        "weight": 3.5,
        "intent_type": "ground_truth_verification",
        "episode_id": "bk-x",
        "verifier_id": "ground_truth",
        "source": "ground_truth_verification",
    }
    # FAILED path uses failure_weight
    rt.trust_network.record_outcome.reset_mock()
    fb.on_event(_evt(EventType.VERIFICATION_FAILED.value, agent_id="agent-7", booking_id="bk-y"))
    call2 = rt.trust_network.record_outcome.call_args
    assert call2.kwargs["weight"] == 0.75
    assert call2.kwargs["episode_id"] == "bk-y"
    assert call2.kwargs["success"] is False
```

---

## Tests

The 12 tests above (Section 4) cover:

| # | Test | Coverage |
|---|---|---|
| 1 | `test_ground_truth_config_trust_feedback_enabled_default_false` | Config field default |
| 2 | `test_ground_truth_config_trust_feedback_success_weight_default` | Config field default |
| 3 | `test_ground_truth_config_trust_feedback_failure_weight_default` | Config field default |
| 4 | `test_on_event_passed_calls_record_outcome_success_true` | PASSED path → success=True |
| 5 | `test_on_event_failed_calls_record_outcome_success_false` | FAILED path → success=False |
| 6 | `test_on_event_rejected_is_noop` | REJECTED no-op (double-counting prevention) |
| 7 | `test_on_event_quarantined_is_noop` | QUARANTINED no-op |
| 8 | `test_on_event_empty_agent_id_is_noop` | Empty/missing agent_id guard (covers both `""` and missing-key) |
| 9 | `test_on_event_missing_trust_network_is_noop` | Missing trust_network guard |
| 10 | `test_on_event_record_outcome_exception_log_and_degrade` | Tier-2 exception handling |
| 11 | `test_on_event_is_sync_not_async` | Sync listener (matches runtime dispatch model) |
| 12 | `test_on_event_passes_record_outcome_kwargs_correctly` | Locked kwargs (intent_type, episode_id, verifier_id, source) + custom weights reach record_outcome |

Test count delta target: **+12**, ceiling **+13** (one boundary discovery allowance). 12 `def test_*` functions in Section 4.

---

## What This Does NOT Change

- **`GroundTruthVerifier`** — UNCHANGED. Existing 11 verifier tests continue to pass.
- **`GroundTruthRejectionGate`** — UNCHANGED. Existing 14 AD-528b tests continue to pass.
- **`VerificationEpisodeWriter`** — UNCHANGED. Existing 3 episode-writer tests continue to pass.
- **`GroundTruthResult` / `RejectionDecision`** — UNCHANGED. v1 reads event payload dicts; never instantiates these dataclasses.
- **`TrustNetwork` / `consensus/trust.py` / `TrustRecord`** — UNCHANGED. AD-528c v1 invokes the existing public `record_outcome` API via dependency injection (`runtime.trust_network`); no signature change.
- **`AD-558` cascade-breaker / dampening / hard floor** — UNCHANGED. Applied internally by `record_outcome` regardless of caller.
- **`events.py` / `EventType`** — UNCHANGED. v1 reuses existing `VERIFICATION_PASSED` and `VERIFICATION_FAILED`. No new enum value.
- **`runtime.add_event_listener`** — UNCHANGED. v1 calls the existing public API.
- **`runtime._emit_event` / `_emit_event_local`** — UNCHANGED. v1 consumes events via the listener path; never emits.
- **Existing AD-528 / AD-528b finalize emit-order** — UNCHANGED. Section 3 SEARCH/REPLACE preserves the existing AD-528 if-block content verbatim plus the additive AD-528c sub-block. The new sub-block is inserted between the AD-528b `else: runtime.ground_truth_rejection_gate = None` line and the existing closing `logger.info("AD-528: ...")`.

---

## Tracking

- `PROGRESS.md` — prepend an `AD-528c CLOSED. Ground-Truth Trust-Network Feedback. Created GroundTruthTrustFeedback in cognitive/ground_truth.py (sync listener, registered via runtime.add_event_listener for VERIFICATION_PASSED + VERIFICATION_FAILED); calls runtime.trust_network.record_outcome(agent_id, success, weight, intent_type="ground_truth_verification", episode_id=booking_id, verifier_id="ground_truth", source="ground_truth_verification") via the public API (ProbOS principle 3 — raw (alpha,beta) storage is internal to TrustNetwork). VERIFICATION_REJECTED NOT consumed in v1 (co-fires with FAILED; double-counting prevention; AD-528c-1). GroundTruthConfig.trust_feedback_enabled (False default) + trust_feedback_success_weight (1.0) + trust_feedback_failure_weight (0.5). Finalize wiring extends existing AD-528 if-block (after AD-528b sub-block); runtime.ground_truth_trust_feedback public attribute. Tier-2 log-and-degrade on record_outcome failure. 12 focused tests pass.` entry. (Builders in Waves 56/57/58 skipped this step; Captain may handle separately.)
- `docs/development/roadmap.md` — flip AD-528c row to ✅ shipped; add deferral entries:
  - **AD-528c-1**: Default-flip of `trust_feedback_enabled` to True + REJECTED-aware weighting (escalate negative weight when rejection gate engaged).
  - **AD-528c-2**: Counselor / Captain alert routing on ground-truth-driven trust-floor hits (tag `TRUST_CASCADE_WARNING` events with source).
  - **AD-528c-3**: AD-558 cascade-breaker integration audit under realistic event volumes.
  - **AD-528c-4**: HXI dashboard surface for "trust impact attributed to ground-truth verification".
  - **AD-528c-5**: Re-aggregation / re-scoring on retraction (transactional trust updates with rollback).
  - **AD-528c-6** *(Commercial)*: Compliance-grade trust attribution / per-jurisdiction trust-update audit trails / GDPR-compliant trust-data export hooks / regulator-facing trust-evidence chain — extension point on `runtime.ground_truth_trust_feedback` + `TrustNetwork.event_log`.
- `DECISIONS.md` — prepend AD-528c entry at top of Era V (or current era).

---

## Acceptance Criteria

1. **All Section 1–4 edits land cleanly.** SEARCH blocks match HEAD `6b24d75` exactly; REPLACE blocks reproduce existing content verbatim plus additive content.
2. **`cognitive/ground_truth.py` compiles** — `python -c "from probos.cognitive.ground_truth import GroundTruthTrustFeedback, GroundTruthRejectionGate, RejectionDecision, GroundTruthVerifier, VerificationEpisodeWriter, GroundTruthResult"` succeeds.
3. **`config.py` compiles + Pydantic validates** — `python -c "from probos.config import GroundTruthConfig; cfg = GroundTruthConfig(); assert cfg.trust_feedback_enabled is False; assert cfg.trust_feedback_success_weight == 1.0; assert cfg.trust_feedback_failure_weight == 0.5; assert cfg.active_rejection_enabled is False"` succeeds.
4. **No new EventType added** — `python -c "from probos.events import EventType; vals = {e.value for e in EventType}; assert 'verification_passed' in vals; assert 'verification_failed' in vals; assert 'verification_rejected' in vals; assert 'work_item_quarantined' in vals"` succeeds (existing values preserved); no NEW value beyond the four already present.
5. **Focused gate passes** — `pytest tests/test_ad528c_trust_feedback.py tests/test_ad528b_active_rejection.py tests/test_ad528_ground_truth.py -v -n 0` returns 40/40 (12 new + 14 AD-528b + 14 AD-528).
6. **Full parallel gate passes** — `pytest tests/ -q -n 8 --dist=loadfile` returns 11292 passed (ceiling 11293), zero new failures.
7. **No `record.alpha = ...` or `record.beta = ...` direct assignment appears in any file modified by this AD.** ProbOS principle 3 — invoke the public `record_outcome` only.
8. **No modification of `events.py` / `consensus/trust.py` / `TrustNetwork` / `TrustRecord`.**
9. **No modification of `GroundTruthVerifier` / `GroundTruthRejectionGate` / `VerificationEpisodeWriter` / `GroundTruthResult` / `RejectionDecision`.**
10. **`on_event` is a sync method**, not `async def`. Test #11 enforces this via `inspect.iscoroutinefunction`.
11. **Listener registration uses `EventType.<NAME>.value` (string)**, not the enum directly. Section 3 finalize block passes `[EventType.VERIFICATION_PASSED.value, EventType.VERIFICATION_FAILED.value]`.
12. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.** Specifically: SOLID (feedback is a single-responsibility listener; depends on `runtime.trust_network` via getattr-injection — Dependency Inversion), three-tier exception handling (`on_event` tier-2 log-and-degrade with structured context), type annotations on all public methods, no bare mutable defaults, structured log messages with what/why/what-next, no `obj._private_attr` access (uses `getattr(self._runtime, "trust_network", None)` for defensive lookup).
