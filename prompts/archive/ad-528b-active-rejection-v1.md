# AD-528b v1 — Ground-Truth Verification: Active Rejection & Quarantine

**Status:** ready
**Dependencies:** AD-528 v1 (`GroundTruthVerifier`, `GroundTruthResult`, `VerificationEpisodeWriter`, `EventType.VERIFICATION_PASSED` / `VERIFICATION_FAILED`, `GroundTruthConfig`, `runtime.ground_truth_verifier` — all shipped Wave 7); AD-680 (`runtime.emit_event` public — shipped); AD-498 (`WorkTypeRegistry.validate_transition` + `BUILTIN_WORK_TYPES` — shipped); existing `WorkItemStore.update_work_item(work_item_id, **updates)` JSON-field path (`workforce.py:1108-1138`)
**Estimated tests:** 14 new (1 new test file `tests/test_ad528b_active_rejection.py`)
**Closes:** GH issue #401

---

## Problem

`GroundTruthVerifier` (`src/probos/cognitive/ground_truth.py`, AD-528 v1, Wave 7) is observation-only — it scores claimed work-item completions against `BookingJournal` + `event_log` evidence and emits `VERIFICATION_PASSED` / `VERIFICATION_FAILED`, but takes no corrective action when verification fails. The module's docstring contracts the gap (`ground_truth.py:1-7`):

```
"""AD-528: Ground-Truth Task Verification.

Cross-references claimed task completions against ``BookingJournal`` entries
and ``event_log`` audit records. Returns a confidence score and a list of
signals that matched (or didn't). Read-only over existing state in v1;
active rejection deferred to AD-528b.
"""
```

The roadmap entry (`docs/development/roadmap.md:6514`) names AD-528b:

> "AD-528b: Ground-Truth Verification — Active Rejection & Quarantine *(Scoped, OSS, Issue #401)* — Extend observation-only ground-truth verification (AD-528 v1) with active rejection: when postcondition checks fail, automatically reject the WorkItem completion claim, revert status to in-progress, and quarantine the agent's output for review. v1 logs discrepancies but takes no corrective action."

**The roadmap "revert status to in-progress" line is structurally infeasible at v1.** `WorkItemStatus.DONE` is a TERMINAL state for the `task` work_type per `workforce.py:160` (`terminal_statuses=frozenset({"done", "failed", "cancelled"})`); `WorkTypeRegistry.validate_transition` at `workforce.py:268-281` rejects ALL transitions FROM terminal statuses (`if from_status in wt.terminal_statuses: return False, f"Cannot transition from terminal status '{from_status}'"`). True "revert from done" requires either adding a `quarantined` status to the work_type's `valid_transitions` list (substantial change to `BUILTIN_WORK_TYPES` + `_TERMINAL_STATUSES` + every test that enumerates valid statuses) or pre-commit interception (run verification BEFORE allowing the `→ done` transition).

**v1 ships pre-commit interception + metadata-only quarantine.** The state-machine extension to add a `quarantined` status is deferred to AD-528b-5; reverting from `done` requires that addition first.

`v1 also ships producer-only — no caller integration.` AD-528 v1 (Wave 7) shipped the verifier with ZERO production callers (verified at HEAD `a5523ab`: `grep "ground_truth_verifier\." src/probos/` and `grep "verification_episode_writer\." src/probos/` both return zero hits). AD-528b v1 follows the same posture — ship the rejection-gate layer + finalize wiring + 14 tests, defer caller integration to AD-528b-2.

This AD plumbs the seam:

```
GroundTruthVerifier (AD-528 v1 — UNCHANGED)
    │
    └── verify(...) → GroundTruthResult     # existing PASSED/FAILED emit unchanged

GroundTruthRejectionGate (NEW, wraps verifier)
    ├── __init__(*, verifier, runtime, emit_event=None, metadata_key="ground_truth_quarantine")
    └── async evaluate(*, booking_id, agent_id, claimed_summary, work_item_id, completed_at=None) → RejectionDecision
            │
            ├── result = await verifier.verify(...)               # existing emit fires
            ├── if result.verified: return RejectionDecision(action="allow", ...)
            ├── # rejection branch
            ├── emit VERIFICATION_REJECTED                         # NEW EventType
            ├── applied = await _apply_quarantine(work_item_id, payload)
            │       │
            │       └── runtime.work_item_store.update_work_item(
            │                 work_item_id,
            │                 metadata={**existing, metadata_key: payload})
            ├── if applied: emit WORK_ITEM_QUARANTINED             # NEW EventType
            └── return RejectionDecision(action="reject", quarantine_metadata=payload, ...)

startup/finalize.py wiring (NEW sub-block inside existing AD-528 if-block)
    if config.ground_truth.active_rejection_enabled and runtime.ground_truth_verifier is not None:
        runtime.ground_truth_rejection_gate = GroundTruthRejectionGate(...)
    else:
        runtime.ground_truth_rejection_gate = None
```

`v1 ships the layer + finalize wiring + tests.` Caller integration (wrap `transition_work_item(..., "done")` to consult the gate), default-flip of `active_rejection_enabled`, Counselor / Captain alert routing on quarantine, re-verification retry workflow, status-machine extension (`quarantined` status on the `task` work_type), trust-network feedback (which is a distinct AD — AD-528c, Wave 59), and commercial overlays are deferred to AD-528b-2 / -1 / -3 / -4 / -5 / AD-528c / -6 *(Commercial)* respectively.

## Solution

v1 ships:

1. **`RejectionDecision`** — new frozen dataclass at module level in `cognitive/ground_truth.py`. Mirrors `GroundTruthResult` shape (`ground_truth.py:23-32`). Fields: `verified: bool`, `score: float`, `action: str` (`"allow"` | `"reject"`), `quarantine_metadata: dict[str, Any]` (default empty), `signals: list[str]` (default empty), `booking_id: str` (default empty), `agent_id: str` (default empty), `work_item_id: str` (default empty). Required-no-default fields first; defaulted fields with `field(default_factory=...)` for mutable types.

2. **`GroundTruthRejectionGate`** — new module-level class in `cognitive/ground_truth.py`, defined AFTER `VerificationEpisodeWriter`. Constructor: `__init__(self, *, verifier: GroundTruthVerifier, runtime: Any, emit_event: Any | None = None, metadata_key: str = "ground_truth_quarantine") -> None`. Public method: `async evaluate(*, booking_id, agent_id, claimed_summary, work_item_id, completed_at=None) -> RejectionDecision`. Private helpers: `async _apply_quarantine(work_item_id, payload) -> bool`, sync `_emit(event_type, payload)`.

3. **`EventType.VERIFICATION_REJECTED`** — new enum value in `events.py`. Inserted immediately after existing `VERIFICATION_FAILED` (line 216). Emitted by `GroundTruthRejectionGate.evaluate` on the rejection branch BEFORE the metadata-apply attempt.

4. **`EventType.WORK_ITEM_QUARANTINED`** — new enum value in `events.py`. Inserted immediately after `VERIFICATION_REJECTED`. Emitted by `GroundTruthRejectionGate.evaluate` ONLY if `_apply_quarantine` succeeded (the metadata key actually landed on the work item).

5. **`GroundTruthConfig.active_rejection_enabled: bool = False`** — Convention #14 + #3 + Wave 55 / 56 / 57 sibling pattern: default False on the transitional flag. AD-528b-1 flips default to True once AD-528b-2 (caller integration) lands.

6. **`GroundTruthConfig.quarantine_metadata_key: str = "ground_truth_quarantine"`** — operator-configurable metadata key. Mirrors `audit_persistence_filename` shape (AD-456d, `config.py:1480`).

7. **`startup/finalize.py` wiring** — single new sub-block inserted INSIDE the existing AD-528 `if config.ground_truth.enabled:` block, AFTER the `verification_episode_writer` assignment and BEFORE the closing `logger.info("AD-528: GroundTruthVerifier wired ...")` line. Constructs `GroundTruthRejectionGate` only when `config.ground_truth.active_rejection_enabled and runtime.ground_truth_verifier is not None`. Sets `runtime.ground_truth_rejection_gate = gate` (greenfield runtime attribute). The OUTER else-branch (existing `else: runtime.ground_truth_verifier = None ; runtime.verification_episode_writer = None` at `finalize.py:1395-1397`) extends to also set `runtime.ground_truth_rejection_gate = None`.

`Backwards compatibility`: every existing AD-528 test (`test_ad528_ground_truth.py` — 14 tests) continues to function. No symbol is removed; no signature is changed; the verifier and episode writer are NOT modified. New `RejectionDecision` and `GroundTruthRejectionGate` are greenfield; new `active_rejection_enabled` defaults False; new `quarantine_metadata_key` defaults to a sensible name. Existing `GroundTruthVerifier(runtime=..., emit_event=..., threshold=...)` and `VerificationEpisodeWriter(runtime=...)` constructions behave identically to today.

### Scope

| Component | Status |
|---|---|
| `RejectionDecision` frozen dataclass | NEW (module-level in `cognitive/ground_truth.py`) |
| `GroundTruthRejectionGate` class (init, evaluate, _apply_quarantine, _emit) | NEW (module-level in `cognitive/ground_truth.py`) |
| `EventType.VERIFICATION_REJECTED` | NEW |
| `EventType.WORK_ITEM_QUARANTINED` | NEW |
| `GroundTruthConfig.active_rejection_enabled` | NEW |
| `GroundTruthConfig.quarantine_metadata_key` | NEW |
| `startup/finalize.py` rejection-gate wiring (sub-block + else-branch extension) | EDIT (additive) |
| `runtime.ground_truth_rejection_gate` attribute (greenfield) | NEW (set in finalize) |
| `tests/test_ad528b_active_rejection.py` (14 tests) | NEW |

### Out of scope (legitimate boundaries — DO NOT BUILD)

- **Caller integration** (wrap `WorkItemStore.transition_work_item(..., "done")` or `BookingService` completion hook to consult `runtime.ground_truth_rejection_gate.evaluate(...)` before allowing the transition). This is the actual producer-side wiring that activates the gate. Deferred to AD-528b-2. v1 sets `runtime.ground_truth_rejection_gate` so the future hook can be a one-line addition; v1 ships the gate with full unit-test coverage but no production callers.
- **Default-flip of `active_rejection_enabled` to True.** Convention #14 + Convention #3. Deferred to AD-528b-1 once AD-528b-2 (caller integration) lands and a fleet-wide rehearsal confirms no false-positive rejections.
- **Counselor / Captain alert routing on `WORK_ITEM_QUARANTINED`.** v1 emits the event but no production handler currently consumes it. Operator dashboards / HXI surface / Counselor alert paths will wire consumers. Deferred to AD-528b-3.
- **Re-verification retry workflow** — agent supplies new evidence, gate re-evaluates, quarantine metadata updates with retry-attempt counter. Deferred to AD-528b-4.
- **State-machine extension** — add `quarantined` status to `task` work_type's `valid_transitions` (and audit `_TERMINAL_STATUSES` accordingly). Enables true "revert from done to quarantined" semantics that the roadmap text envisioned. v1 ships PRE-COMMIT gate + metadata-only quarantine; state addition is structural change touching `BUILTIN_WORK_TYPES` (`workforce.py:140`) + every test enumerating valid statuses. Deferred to AD-528b-5.
- **Trust-network feedback** — verified completions raise trust; failed verifications lower trust with graduated severity. **This is a DISTINCT AD — AD-528c, Wave 59.** v1 of AD-528b emits `VERIFICATION_REJECTED` / `WORK_ITEM_QUARANTINED` as observable signals; AD-528c will subscribe and feed `TrustNetwork.update(...)`. v1 has ZERO `import probos.consensus.trust` and ZERO `runtime.trust_network` references.
- **Commercial overlays** (*compliance-grade quarantine workflows / SOX evidence chain / GDPR right-to-erasure attestation / regulatory audit-export hooks*). *(Commercial)* — extension point only; v1's `RejectionDecision.quarantine_metadata` dict + `WORK_ITEM_QUARANTINED` event subscription IS the plug-in seam where commercial overlays attach. Deferred to AD-528b-6.
- **`ReconciliationEscalator` (AD-451) integration.** AD-451 covers verifier-vs-verifier disagreement; AD-528 covers did-it-happen-at-all; AD-528b covers what-do-we-do-when-it-didn't-happen. The three are orthogonal at v1. Future AD-528b-N may emit a `VerificationRejectionResult` that ReconciliationEscalator can ingest — v1 does not wire that.
- **Episode-store records for rejection events.** `VerificationEpisodeWriter` (AD-528, `ground_truth.py:188-244`) writes one episode per verification. v1 of AD-528b does NOT extend it to write rejection-specific episodes. The two new EventTypes ARE the durable record at v1; episode-store integration for rejection metadata is a future polish.
- **No new pool, agent, or module beyond the 1 new test file.** No EventType beyond the two listed. No new Pydantic config class — fields append to existing `GroundTruthConfig`. No new file beyond `tests/test_ad528b_active_rejection.py`.
- **No modification of `GroundTruthVerifier`.** Existing verifier behaviour is preserved bit-for-bit. The gate WRAPS the verifier — does not modify it.
- **No modification of `VerificationEpisodeWriter`.** Orthogonal to active rejection.
- **No modification of `_TERMINAL_STATUSES` (`workforce.py:610`) or `BUILTIN_WORK_TYPES` (`workforce.py:140`).** State-machine extension is AD-528b-5.
- **No modification of `WorkItemStore.update_work_item` (`workforce.py:1108-1138`).** The merge happens IN THE GATE before calling update_work_item — the store sees a complete `metadata` dict.
- **No coupling to `EarnedAgency` / `CredentialStore` / `EgressPolicy` / `RuntimeSandbox` / `AuditLog` / any AD-456 cluster surface.** AD-528b is a pure cognitive-layer extension.

---

## Verified Against Codebase (HEAD post-Wave-57, `a5523ab`, 2026-05-05)

| Symbol | Path | Line | Verifying line |
|---|---|---|---|
| `GroundTruthVerifier` class (wrap target) | `src/probos/cognitive/ground_truth.py` | 37 | `class GroundTruthVerifier:` |
| `GroundTruthResult` frozen dataclass (mirror target) | `src/probos/cognitive/ground_truth.py` | 23-32 | `@dataclass(frozen=True)` … `class GroundTruthResult:` … `verified: bool` |
| `GroundTruthVerifier.verify` signature | `src/probos/cognitive/ground_truth.py` | 73-80 | `async def verify(self, *, booking_id: str, agent_id: str, claimed_summary: str, completed_at: float \| None = None,) -> GroundTruthResult:` |
| `GroundTruthVerifier._emit` (sync, sibling shape) | `src/probos/cognitive/ground_truth.py` | 163-181 | `def _emit(self, result: GroundTruthResult) -> None:` … `self._emit_event(et, ...)` |
| `VerificationEpisodeWriter` class (insertion-anchor sibling — new code goes AFTER) | `src/probos/cognitive/ground_truth.py` | 188 | `class VerificationEpisodeWriter:` |
| `VerificationEpisodeWriter.write` final `return False` (insertion target — last line of file at HEAD) | `src/probos/cognitive/ground_truth.py` | 244 | `return False` |
| `from __future__ import annotations` (already present — enables forward refs) | `src/probos/cognitive/ground_truth.py` | 9 | `from __future__ import annotations` |
| Existing imports (`logging`, `time`, `dataclass`/`field`, `TYPE_CHECKING`, `Any`, `EventType`) | `src/probos/cognitive/ground_truth.py` | 11-16 | `import logging` … `import time` … `from dataclasses import dataclass, field` … `from typing import TYPE_CHECKING, Any` … `from probos.events import EventType` |
| `EventType.VERIFICATION_PASSED` (existing AD-528 enum) | `src/probos/events.py` | 215 | `VERIFICATION_PASSED = "verification_passed"  # AD-528` |
| `EventType.VERIFICATION_FAILED` (insertion-anchor — new lines go IMMEDIATELY AFTER) | `src/probos/events.py` | 216 | `VERIFICATION_FAILED = "verification_failed"  # AD-528` |
| `EventType.RESOURCE_ALLOCATED` (sibling — line below `VERIFICATION_FAILED`, used as REPLACE re-emit anchor) | `src/probos/events.py` | 217 | `RESOURCE_ALLOCATED = "resource_allocated"  # AD-467` |
| `GroundTruthConfig` Pydantic class | `src/probos/config.py` | 1292 | `class GroundTruthConfig(BaseModel):` |
| `GroundTruthConfig` existing 4 fields | `src/probos/config.py` | 1295-1298 | `enabled: bool = True` … `threshold: float = Field(default=0.75, ge=0.0, le=1.0)` … `event_window_seconds: float = Field(default=600.0, ge=10.0)` … `write_episode: bool = True` |
| `OperationsConfig` (sibling — class after `GroundTruthConfig`, used as REPLACE re-emit anchor) | `src/probos/config.py` | 1300 | `class OperationsConfig(BaseModel):` |
| AD-528 finalize block (extension target) | `src/probos/startup/finalize.py` | 1373-1397 | `if config.ground_truth.enabled:` … `runtime.ground_truth_verifier = None` … `runtime.verification_episode_writer = None` |
| `finalize_startup` is async (allows existing `await` semantics in extended block) | `src/probos/startup/finalize.py` | 848 | `async def finalize_startup(` |
| Existing AD-528 if-block body — verifier construction, episode-writer if/else, closing logger.info, OUTER else-branch | `src/probos/startup/finalize.py` | 1375-1397 | `from probos.cognitive.ground_truth import (GroundTruthVerifier, VerificationEpisodeWriter,)` … `runtime.ground_truth_verifier = GroundTruthVerifier(...)` … `if config.ground_truth.write_episode:` … `runtime.verification_episode_writer = VerificationEpisodeWriter(runtime=runtime,)` … `else: runtime.verification_episode_writer = None` … `logger.info("AD-528: GroundTruthVerifier wired ...")` … `else: runtime.ground_truth_verifier = None ; runtime.verification_episode_writer = None` |
| `WorkItemStore.update_work_item` signature (gate calls this) | `src/probos/workforce.py` | 1108 | `async def update_work_item(self, work_item_id: str, **updates: Any) -> WorkItem \| None:` |
| `WorkItemStore.get_work_item` signature (gate calls this) | `src/probos/workforce.py` | 1054 | `async def get_work_item(self, work_item_id: str) -> WorkItem \| None:` |
| `_JSON_FIELDS` includes `metadata` (auto-`json.dumps`) | `src/probos/workforce.py` | 891-895 | `_JSON_FIELDS = frozenset({...,  "metadata", ...})` |
| `_IMMUTABLE_FIELDS` does NOT include `metadata` | `src/probos/workforce.py` | 898 | `_IMMUTABLE_FIELDS = frozenset({"id", "created_at", "created_by"})` |
| `WorkItem.metadata` field default | `src/probos/workforce.py` | 586 | `metadata: dict[str, Any] = field(default_factory=dict)` |
| `task` work_type terminal statuses (rationale for pre-commit gate) | `src/probos/workforce.py` | 160 | `terminal_statuses=frozenset({"done", "failed", "cancelled"})` |
| `validate_transition` rejects FROM-terminal | `src/probos/workforce.py` | 271-272 | `if from_status in wt.terminal_statuses: return False, ...` |
| Existing AD-528 tests (no modification) | `tests/test_ad528_ground_truth.py` | 73-263 | 14 tests pass at HEAD |

`RejectionDecision`, `GroundTruthRejectionGate`, `GroundTruthRejectionGate.evaluate`, `GroundTruthRejectionGate._apply_quarantine`, `GroundTruthRejectionGate._emit`, `EventType.VERIFICATION_REJECTED`, `EventType.WORK_ITEM_QUARANTINED`, `GroundTruthConfig.active_rejection_enabled`, `GroundTruthConfig.quarantine_metadata_key`, `runtime.ground_truth_rejection_gate`, `tests/test_ad528b_active_rejection.py` — all greenfield, verified zero hits at HEAD `a5523ab`.

`AD-528a` artifact verification — zero hits in `prompts/`, `prompts/archive/`, `DECISIONS.md`, `decisions-era-*.md`, `PROGRESS.md`, `progress-era-*.md`, `docs/development/roadmap.md` at HEAD `a5523ab`. AD-528b is the b-tier root with no prior `a` sibling.

---

## Implementation

### Section 0 — Event Types

**File:** `src/probos/events.py`

`SEARCH` block (line 216 plus its immediate context, lines 215-217):
```python
    VERIFICATION_PASSED = "verification_passed"  # AD-528
    VERIFICATION_FAILED = "verification_failed"  # AD-528
    RESOURCE_ALLOCATED = "resource_allocated"  # AD-467
```

`REPLACE`:
```python
    VERIFICATION_PASSED = "verification_passed"  # AD-528
    VERIFICATION_FAILED = "verification_failed"  # AD-528
    VERIFICATION_REJECTED = "verification_rejected"  # AD-528b
    WORK_ITEM_QUARANTINED = "work_item_quarantined"  # AD-528b
    RESOURCE_ALLOCATED = "resource_allocated"  # AD-467
```

### Section 1 — Config Fields

**File:** `src/probos/config.py`

`SEARCH` block (the `GroundTruthConfig` body plus the immediately-following blank line and `OperationsConfig` head, lines 1292-1300):
```python
class GroundTruthConfig(BaseModel):
    """Ground-truth task verification configuration (AD-528)."""

    enabled: bool = True
    threshold: float = Field(default=0.75, ge=0.0, le=1.0)
    event_window_seconds: float = Field(default=600.0, ge=10.0)
    write_episode: bool = True


class OperationsConfig(BaseModel):
```

`REPLACE`:
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

### Section 2 — `cognitive/ground_truth.py` extensions

**File:** `src/probos/cognitive/ground_truth.py`

#### Section 2a — `RejectionDecision` frozen dataclass (module-level)

`SEARCH` block (the trailing lines of `VerificationEpisodeWriter.write`, lines 235-244 — anchored on the file's final `return False`):
```python
        try:
            await em.store(episode)
            return True
        except Exception:
            logger.warning(
                "AD-528: episode store failed (booking_id=%s, agent_id=%s)",
                result.booking_id, result.agent_id, exc_info=True,
            )
            return False
```

`REPLACE`:
```python
        try:
            await em.store(episode)
            return True
        except Exception:
            logger.warning(
                "AD-528: episode store failed (booking_id=%s, agent_id=%s)",
                result.booking_id, result.agent_id, exc_info=True,
            )
            return False


# ---------------------------------------------------------------------------
# AD-528b: Active Rejection & Quarantine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RejectionDecision:
    """Outcome of a ``GroundTruthRejectionGate.evaluate()`` call.

    ``action`` is ``"allow"`` when the underlying verifier returned
    ``verified=True``; ``"reject"`` when the gate took the rejection branch.
    On the reject path, ``quarantine_metadata`` carries the payload that was
    (or would be) merged into the work item's metadata under the gate's
    configured ``metadata_key``. On the allow path, ``quarantine_metadata``
    is empty.

    Frozen because consumers (HXI surfaces, Counselor alert paths, and the
    future AD-528b-2 caller-integration wiring) need a value-type they can
    pass around without defensive-copy.
    """

    verified: bool
    score: float
    action: str  # "allow" | "reject"
    quarantine_metadata: dict[str, Any] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    booking_id: str = ""
    agent_id: str = ""
    work_item_id: str = ""
```

#### Section 2b — `GroundTruthRejectionGate` class (module-level)

`SEARCH` block (the trailing lines of Section 2a's REPLACE — `RejectionDecision` field declarations):
```python
    verified: bool
    score: float
    action: str  # "allow" | "reject"
    quarantine_metadata: dict[str, Any] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    booking_id: str = ""
    agent_id: str = ""
    work_item_id: str = ""
```

`REPLACE`:
```python
    verified: bool
    score: float
    action: str  # "allow" | "reject"
    quarantine_metadata: dict[str, Any] = field(default_factory=dict)
    signals: list[str] = field(default_factory=list)
    booking_id: str = ""
    agent_id: str = ""
    work_item_id: str = ""


class GroundTruthRejectionGate:
    """Wraps ``GroundTruthVerifier`` with a pre-commit rejection decision +
    metadata-only quarantine.

    v1 surface: callers (deferred to AD-528b-2) invoke ``evaluate(...)``
    BEFORE attempting a ``→ done`` transition on a work item. If verification
    passes, ``evaluate`` returns ``RejectionDecision(action="allow")`` and
    the caller proceeds. If verification fails, the gate emits
    ``VERIFICATION_REJECTED``, attempts to merge a quarantine payload into
    the work item's metadata via
    ``runtime.work_item_store.update_work_item(work_item_id, metadata=...)``,
    emits ``WORK_ITEM_QUARANTINED`` on successful merge, and returns
    ``RejectionDecision(action="reject", quarantine_metadata=...)``.

    Status-machine semantics: v1 does NOT mutate work-item status. The
    caller decides whether to transition the item to ``failed``, keep it
    in ``in_progress``, or escalate. State-machine extension (adding a
    ``quarantined`` status to the ``task`` work_type) is deferred to
    AD-528b-5.

    Trust-network feedback (raise/lower trust on PASSED/FAILED/REJECTED)
    is a distinct AD — AD-528c (Wave 59). v1 of this class has zero
    coupling to ``runtime.trust_network`` or ``probos.consensus.trust``.
    """

    DEFAULT_METADATA_KEY = "ground_truth_quarantine"

    def __init__(
        self,
        *,
        verifier: GroundTruthVerifier,
        runtime: Any,
        emit_event: Any | None = None,
        metadata_key: str = DEFAULT_METADATA_KEY,
    ) -> None:
        self._verifier = verifier
        self._runtime = runtime
        self._emit_event = emit_event
        self._metadata_key = metadata_key

    async def evaluate(
        self,
        *,
        booking_id: str,
        agent_id: str,
        claimed_summary: str,
        work_item_id: str,
        completed_at: float | None = None,
    ) -> RejectionDecision:
        """Evaluate a claimed completion; return allow/reject decision."""
        result = await self._verifier.verify(
            booking_id=booking_id,
            agent_id=agent_id,
            claimed_summary=claimed_summary,
            completed_at=completed_at,
        )
        if result.verified:
            return RejectionDecision(
                verified=True,
                score=result.score,
                action="allow",
                signals=list(result.signals),
                booking_id=booking_id,
                agent_id=agent_id,
                work_item_id=work_item_id,
            )

        # Rejection branch. Emit VERIFICATION_REJECTED first (the cognitive
        # decision is independent of whether the metadata persists), then
        # attempt the metadata merge, then emit WORK_ITEM_QUARANTINED only
        # if the merge succeeded.
        payload: dict[str, Any] = {
            "score": result.score,
            "signals": list(result.signals),
            "rejected_at": time.time(),
            "reason": "ground_truth_score_below_threshold",
            "booking_id": booking_id,
            "agent_id": agent_id,
        }
        self._emit(
            EventType.VERIFICATION_REJECTED,
            {**payload, "work_item_id": work_item_id},
        )
        applied = await self._apply_quarantine(work_item_id, payload)
        if applied:
            self._emit(
                EventType.WORK_ITEM_QUARANTINED,
                {
                    **payload,
                    "work_item_id": work_item_id,
                    "metadata_key": self._metadata_key,
                },
            )
        return RejectionDecision(
            verified=False,
            score=result.score,
            action="reject",
            quarantine_metadata=payload,
            signals=list(result.signals),
            booking_id=booking_id,
            agent_id=agent_id,
            work_item_id=work_item_id,
        )

    async def _apply_quarantine(
        self, work_item_id: str, payload: dict[str, Any]
    ) -> bool:
        """Merge quarantine payload into work item metadata. Tier-2 log-and-degrade.

        Read-modify-write: fetch the current work item, copy its existing
        metadata, set ``existing[metadata_key] = payload``, write the merged
        dict back via ``update_work_item``. Existing keys in the work item's
        metadata survive the merge.

        Returns True if the merge persisted; False on any failure (missing
        runtime, missing work_item_store, missing work item, store exception).
        Failures are logged at WARNING with ``exc_info=True`` per the
        copilot-instructions tier-2 rule — ``evaluate`` has already emitted
        ``VERIFICATION_REJECTED``, so a metadata-apply failure must NOT
        propagate to the caller.
        """
        rt = self._runtime
        if rt is None or not work_item_id:
            return False
        store = getattr(rt, "work_item_store", None)
        if store is None:
            return False
        try:
            item = await store.get_work_item(work_item_id)
            if item is None:
                return False
            existing_meta = dict(getattr(item, "metadata", None) or {})
            existing_meta[self._metadata_key] = payload
            await store.update_work_item(work_item_id, metadata=existing_meta)
            return True
        except Exception:
            logger.warning(
                "AD-528b: quarantine metadata apply failed (work_item_id=%s, key=%s)",
                work_item_id, self._metadata_key, exc_info=True,
            )
            return False

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

### Section 3 — Finalize Wiring

**File:** `src/probos/startup/finalize.py`

`SEARCH` block (the existing AD-528 if-block including its leading 2 comment lines, lines 1373-1397):
```python
    # AD-528: Ground-Truth Task Verification (v1: read-only scoring + emit;
    # active rejection deferred to AD-528b)
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
        logger.info(
            "AD-528: GroundTruthVerifier wired (threshold=%.2f, window=%.0fs)",
            config.ground_truth.threshold,
            config.ground_truth.event_window_seconds,
        )
    else:
        runtime.ground_truth_verifier = None
        runtime.verification_episode_writer = None
```

`REPLACE`:
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

### Section 4 — Tests

**File:** `tests/test_ad528b_active_rejection.py` (NEW)

Full test file:

```python
"""AD-528b: Ground-Truth Active Rejection & Quarantine tests.

Wraps the existing AD-528 GroundTruthVerifier with a rejection gate that
takes corrective action when verification fails: emits VERIFICATION_REJECTED,
attempts to merge a quarantine payload into the work item's metadata via
WorkItemStore.update_work_item, and emits WORK_ITEM_QUARANTINED when the
merge succeeds. v1 surfaces the layer; caller integration is AD-528b-2.
"""

from __future__ import annotations

import dataclasses
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from probos.cognitive.ground_truth import (
    GroundTruthRejectionGate,
    GroundTruthResult,
    GroundTruthVerifier,
    RejectionDecision,
)
from probos.config import GroundTruthConfig
from probos.events import EventType


# ----- Helpers -----


def _journal_entry(*, journal_type="working", duration=10.0, tokens=500, billable=True):
    return SimpleNamespace(
        journal_type=journal_type,
        duration_seconds=duration,
        tokens_consumed=tokens,
        billable=billable,
    )


def _make_runtime_with_store(
    *,
    journal_entries=None,
    events=None,
    work_item=None,
    update_returns=None,
    update_side_effect=None,
):
    """Build a SimpleNamespace runtime with AsyncMock work_item_store + event_log."""
    rt = SimpleNamespace()
    store = SimpleNamespace()
    if journal_entries is not None:
        store.get_booking_journal = AsyncMock(return_value=journal_entries)
    else:
        store.get_booking_journal = AsyncMock(return_value=[])
    store.get_work_item = AsyncMock(return_value=work_item)
    if update_side_effect is not None:
        store.update_work_item = AsyncMock(side_effect=update_side_effect)
    else:
        store.update_work_item = AsyncMock(return_value=update_returns)
    rt.work_item_store = store
    if events is not None:
        log = SimpleNamespace()
        log.query = AsyncMock(return_value=events)
        rt.event_log = log
    else:
        rt.event_log = None
    return rt, store


def _make_gate(rt, *, emit=None, metadata_key="ground_truth_quarantine", threshold=0.75):
    """Construct a GroundTruthVerifier + GroundTruthRejectionGate pair."""
    if emit is None:
        emit = MagicMock()
    verifier = GroundTruthVerifier(
        runtime=rt, emit_event=emit, threshold=threshold,
    )
    gate = GroundTruthRejectionGate(
        verifier=verifier,
        runtime=rt,
        emit_event=emit,
        metadata_key=metadata_key,
    )
    return gate, verifier, emit


# ----- 1-2: EventTypes -----


def test_event_type_verification_rejected_exists():
    assert EventType.VERIFICATION_REJECTED.value == "verification_rejected"


def test_event_type_work_item_quarantined_exists():
    assert EventType.WORK_ITEM_QUARANTINED.value == "work_item_quarantined"


# ----- 3-4: Config defaults -----


def test_ground_truth_config_active_rejection_default_false():
    cfg = GroundTruthConfig()
    assert cfg.active_rejection_enabled is False


def test_ground_truth_config_quarantine_metadata_key_default():
    cfg = GroundTruthConfig()
    assert cfg.quarantine_metadata_key == "ground_truth_quarantine"


# ----- 5: RejectionDecision dataclass shape -----


def test_rejection_decision_dataclass_shape():
    fields = {f.name: f for f in dataclasses.fields(RejectionDecision)}
    assert set(fields.keys()) == {
        "verified", "score", "action",
        "quarantine_metadata", "signals",
        "booking_id", "agent_id", "work_item_id",
    }
    # Frozen
    decision = RejectionDecision(verified=True, score=1.0, action="allow")
    with pytest.raises(dataclasses.FrozenInstanceError):
        decision.action = "reject"  # type: ignore[misc]
    # Mutable defaults via default_factory (not bare {})
    a = RejectionDecision(verified=True, score=1.0, action="allow")
    b = RejectionDecision(verified=True, score=1.0, action="allow")
    assert a.quarantine_metadata is not b.quarantine_metadata
    assert a.signals is not b.signals


# ----- 6: evaluate allow path -----


@pytest.mark.asyncio
async def test_evaluate_allow_when_verified():
    completed_at = time.time()
    rt, _store = _make_runtime_with_store(
        journal_entries=[_journal_entry(duration=10.0, tokens=500, billable=True)],
        events=[{"timestamp": completed_at - 30}],
    )
    gate, _verifier, emit = _make_gate(rt)
    decision = await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="did the thing",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    assert decision.verified is True
    assert decision.action == "allow"
    assert decision.score == 1.0
    assert decision.quarantine_metadata == {}
    assert decision.work_item_id == "wi1"
    # The verifier's PASSED emit fired; the gate's REJECTED/QUARANTINED did NOT.
    emitted_types = [c.args[0] for c in emit.call_args_list]
    assert EventType.VERIFICATION_PASSED in emitted_types
    assert EventType.VERIFICATION_REJECTED not in emitted_types
    assert EventType.WORK_ITEM_QUARANTINED not in emitted_types


# ----- 7: evaluate reject path -----


@pytest.mark.asyncio
async def test_evaluate_reject_when_unverified():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, _store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, _emit = _make_gate(rt)
    decision = await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="claimed",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    assert decision.verified is False
    assert decision.action == "reject"
    assert decision.score == 0.0
    assert decision.quarantine_metadata["reason"] == "ground_truth_score_below_threshold"
    assert decision.quarantine_metadata["booking_id"] == "bk1"
    assert decision.quarantine_metadata["agent_id"] == "a1"
    assert "rejected_at" in decision.quarantine_metadata
    assert decision.signals == []


# ----- 8: emit VERIFICATION_REJECTED on reject path -----


@pytest.mark.asyncio
async def test_evaluate_emits_verification_rejected_on_reject():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, _store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, emit = _make_gate(rt)
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="claimed",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    emitted_types = [c.args[0] for c in emit.call_args_list]
    # FAILED fires inside verifier.verify; REJECTED fires from the gate.
    assert EventType.VERIFICATION_FAILED in emitted_types
    assert EventType.VERIFICATION_REJECTED in emitted_types


# ----- 9: no REJECTED/QUARANTINED on allow path -----


@pytest.mark.asyncio
async def test_evaluate_does_not_emit_rejected_or_quarantined_on_allow():
    completed_at = time.time()
    rt, _store = _make_runtime_with_store(
        journal_entries=[_journal_entry(duration=10.0, tokens=500, billable=True)],
        events=[{"timestamp": completed_at - 30}],
    )
    gate, _verifier, emit = _make_gate(rt)
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    emitted_types = [c.args[0] for c in emit.call_args_list]
    assert EventType.VERIFICATION_REJECTED not in emitted_types
    assert EventType.WORK_ITEM_QUARANTINED not in emitted_types


# ----- 10: quarantine metadata applied to work item -----


@pytest.mark.asyncio
async def test_evaluate_applies_quarantine_metadata_to_work_item():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, _emit = _make_gate(rt, metadata_key="gt_quarantine_v1")
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    store.update_work_item.assert_awaited_once()
    call_args = store.update_work_item.await_args
    assert call_args.args == ("wi1",)
    merged = call_args.kwargs["metadata"]
    assert "gt_quarantine_v1" in merged
    payload = merged["gt_quarantine_v1"]
    assert payload["reason"] == "ground_truth_score_below_threshold"
    assert payload["booking_id"] == "bk1"


# ----- 11: existing metadata preserved -----


@pytest.mark.asyncio
async def test_evaluate_preserves_existing_work_item_metadata():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={"sentinel": "keep_me", "other": 42})
    rt, store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, _emit = _make_gate(rt)
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    merged = store.update_work_item.await_args.kwargs["metadata"]
    assert merged["sentinel"] == "keep_me"
    assert merged["other"] == 42
    assert "ground_truth_quarantine" in merged


# ----- 12: WORK_ITEM_QUARANTINED emitted after successful apply -----


@pytest.mark.asyncio
async def test_evaluate_emits_work_item_quarantined_after_apply():
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, _store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
    )
    gate, _verifier, emit = _make_gate(rt)
    await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    emitted = [c.args for c in emit.call_args_list]
    quarantined_calls = [
        (et, p) for (et, p) in emitted if et == EventType.WORK_ITEM_QUARANTINED
    ]
    assert len(quarantined_calls) == 1
    _et, payload = quarantined_calls[0]
    assert payload["work_item_id"] == "wi1"
    assert payload["metadata_key"] == "ground_truth_quarantine"
    assert payload["reason"] == "ground_truth_score_below_threshold"


# ----- 13: missing work_item_store handled gracefully -----


@pytest.mark.asyncio
async def test_evaluate_handles_missing_work_item_store_gracefully():
    completed_at = time.time()
    rt = SimpleNamespace()
    rt.work_item_store = None  # No store available
    rt.event_log = None
    emit = MagicMock()
    verifier = GroundTruthVerifier(runtime=rt, emit_event=emit)
    gate = GroundTruthRejectionGate(verifier=verifier, runtime=rt, emit_event=emit)
    decision = await gate.evaluate(
        booking_id="bk1",
        agent_id="a1",
        claimed_summary="x",
        work_item_id="wi1",
        completed_at=completed_at,
    )
    # Decision is still rejected; quarantine apply silently fails.
    assert decision.action == "reject"
    emitted_types = [c.args[0] for c in emit.call_args_list]
    assert EventType.VERIFICATION_REJECTED in emitted_types
    assert EventType.WORK_ITEM_QUARANTINED not in emitted_types


# ----- 14: update_work_item exception swallowed (tier-2 log-and-degrade) -----


@pytest.mark.asyncio
async def test_evaluate_handles_update_exception_log_and_degrade(caplog):
    import logging
    completed_at = time.time()
    work_item = SimpleNamespace(metadata={})
    rt, _store = _make_runtime_with_store(
        journal_entries=[],
        events=[],
        work_item=work_item,
        update_side_effect=RuntimeError("disk full"),
    )
    gate, _verifier, emit = _make_gate(rt)
    with caplog.at_level(logging.WARNING):
        decision = await gate.evaluate(
            booking_id="bk1",
            agent_id="a1",
            claimed_summary="x",
            work_item_id="wi1",
            completed_at=completed_at,
        )
    # Exception swallowed; decision still produced; QUARANTINED NOT emitted.
    assert decision.action == "reject"
    emitted_types = [c.args[0] for c in emit.call_args_list]
    assert EventType.VERIFICATION_REJECTED in emitted_types
    assert EventType.WORK_ITEM_QUARANTINED not in emitted_types
    assert any(
        "AD-528b: quarantine metadata apply failed" in rec.getMessage()
        for rec in caplog.records
    )
```

---

## Tests

The 14 tests above (Section 4) cover:

| # | Test | Coverage |
|---|---|---|
| 1 | `test_event_type_verification_rejected_exists` | EventType added |
| 2 | `test_event_type_work_item_quarantined_exists` | EventType added |
| 3 | `test_ground_truth_config_active_rejection_default_false` | Config field default |
| 4 | `test_ground_truth_config_quarantine_metadata_key_default` | Config field default |
| 5 | `test_rejection_decision_dataclass_shape` | Frozen dataclass + default_factory |
| 6 | `test_evaluate_allow_when_verified` | Allow path semantics |
| 7 | `test_evaluate_reject_when_unverified` | Reject path semantics + payload shape |
| 8 | `test_evaluate_emits_verification_rejected_on_reject` | Reject-event emission |
| 9 | `test_evaluate_does_not_emit_rejected_or_quarantined_on_allow` | Negative-emit on allow |
| 10 | `test_evaluate_applies_quarantine_metadata_to_work_item` | Metadata write + configurable key |
| 11 | `test_evaluate_preserves_existing_work_item_metadata` | Read-modify-write merge |
| 12 | `test_evaluate_emits_work_item_quarantined_after_apply` | Quarantine-event payload |
| 13 | `test_evaluate_handles_missing_work_item_store_gracefully` | Graceful degrade (no store) |
| 14 | `test_evaluate_handles_update_exception_log_and_degrade` | Tier-2 exception handling |

Test count delta target: **+14**, ceiling **+15**.

---

## What This Does NOT Change

- **`GroundTruthVerifier`** — UNCHANGED. Existing 11 verifier tests at `tests/test_ad528_ground_truth.py:73-218` continue to pass.
- **`VerificationEpisodeWriter`** — UNCHANGED. Existing 3 writer tests at `tests/test_ad528_ground_truth.py:222-263` continue to pass.
- **`AuditLog` / `RuntimeSandbox` / `CredentialStore` / `EgressPolicy`** — UNCHANGED. AD-456 cluster orthogonal.
- **`TrustNetwork` / `runtime.trust_network` / `consensus/trust.py`** — UNCHANGED. AD-528c (Wave 59) territory; v1 of AD-528b has zero coupling.
- **`ReconciliationEscalator` (AD-451)** — UNCHANGED. Future seam noted in module docstring.
- **`WorkItemStore.update_work_item`** — UNCHANGED. The gate calls the existing API; no signature or behaviour change.
- **`WorkItemStore.transition_work_item`** — UNCHANGED. AD-528b-2 (caller integration, deferred) will wrap this.
- **`WorkItem` dataclass** — UNCHANGED. The quarantine metadata uses the existing `metadata: dict[str, Any]` field.
- **`BUILTIN_WORK_TYPES` / `_TERMINAL_STATUSES` / `WorkTypeRegistry`** — UNCHANGED. AD-528b-5 (state-machine extension, deferred) will add a `quarantined` status.
- **Existing AD-528 finalize emit-order** — UNCHANGED. Section 3 SEARCH/REPLACE preserves the existing `runtime.ground_truth_verifier = ...` and `runtime.verification_episode_writer = ...` lines verbatim, AND preserves the existing closing `logger.info("AD-528: ...")`. The new sub-block is inserted between the episode-writer assignment and the existing logger.info.

---

## Tracking

- `PROGRESS.md` — prepend an `AD-528b CLOSED. Ground-Truth Active Rejection & Quarantine. Created GroundTruthRejectionGate + RejectionDecision in cognitive/ground_truth.py; added EventType.VERIFICATION_REJECTED / WORK_ITEM_QUARANTINED; GroundTruthConfig.active_rejection_enabled (False default) + quarantine_metadata_key; finalize wiring extends existing AD-528 if-block; runtime.ground_truth_rejection_gate public attribute; pre-commit gate + metadata-only quarantine (state-machine "quarantined" status deferred to AD-528b-5; caller integration deferred to AD-528b-2). 14 focused tests pass.` entry. (Builders in Waves 56/57 skipped this step; Captain may handle separately.)
- `docs/development/roadmap.md` — flip AD-528b row to ✅ shipped; add deferral entries:
  - **AD-528b-1**: Default-flip of `active_rejection_enabled` to True once AD-528b-2 lands.
  - **AD-528b-2**: Caller integration — wrap `WorkItemStore.transition_work_item(..., "done")` (or BookingService completion hook) to consult `runtime.ground_truth_rejection_gate.evaluate(...)`.
  - **AD-528b-3**: Counselor / Captain alert routing on `WORK_ITEM_QUARANTINED` (HXI surface + alert paths).
  - **AD-528b-4**: Re-verification retry workflow (agent supplies new evidence; gate re-evaluates).
  - **AD-528b-5**: State-machine extension — add `quarantined` status to `task` work_type's `valid_transitions`.
  - **AD-528b-6** *(Commercial)*: Compliance-grade quarantine workflows / SOX evidence chain / GDPR right-to-erasure attestation / regulatory audit-export hooks — extension point on `RejectionDecision.quarantine_metadata` + `WORK_ITEM_QUARANTINED` event.
- `DECISIONS.md` — prepend AD-528b entry at top of Era V (or current era).

---

## Acceptance Criteria

1. **All Section 0–4 edits land cleanly.** SEARCH blocks match HEAD `a5523ab` exactly; REPLACE blocks reproduce existing content verbatim plus additive content.
2. **`cognitive/ground_truth.py` compiles** — `python -c "from probos.cognitive.ground_truth import GroundTruthRejectionGate, RejectionDecision, GroundTruthVerifier, VerificationEpisodeWriter, GroundTruthResult"` succeeds.
3. **`config.py` compiles + Pydantic validates** — `python -c "from probos.config import GroundTruthConfig; cfg = GroundTruthConfig(); assert cfg.active_rejection_enabled is False; assert cfg.quarantine_metadata_key == 'ground_truth_quarantine'"` succeeds.
4. **`events.py` enum unique-value invariant holds** — `python -c "from probos.events import EventType; assert len({e.value for e in EventType}) == len(list(EventType))"` succeeds.
5. **Focused gate passes** — `pytest tests/test_ad528b_active_rejection.py tests/test_ad528_ground_truth.py -v -n 0` returns 28/28 (14 new + 14 existing).
6. **Full parallel gate passes** — `pytest tests/ -q -n 8 --dist=loadfile` returns 11280 passed (ceiling 11281), zero new failures.
7. **No `import probos.consensus.trust` and no `runtime.trust_network` reference appears in any file modified by this AD.** AD-528c (Wave 59) territory.
8. **No modification of `BUILTIN_WORK_TYPES` / `_TERMINAL_STATUSES` / `WorkTypeRegistry` / `WorkItemStore.update_work_item` / `WorkItem` dataclass.**
9. **No modification of `GroundTruthVerifier` / `VerificationEpisodeWriter` / `GroundTruthResult`.**
10. **Verify all changes comply with the Engineering Principles in `.github/copilot-instructions.md`.** Specifically: SOLID (gate is a single-responsibility wrapper around verifier), three-tier exception handling (`_apply_quarantine` and `_emit` both tier-2 log-and-degrade with structured context), type annotations on all public methods, no bare mutable defaults (`field(default_factory=dict)` / `field(default_factory=list)` for `RejectionDecision`), structured log messages with what/why/what-next.
