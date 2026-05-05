# WAVE 58 DISPATCH — AD-528b v1 Ground-Truth Active Rejection & Quarantine

**Wave id:** 58
**Single AD:** AD-528b
**Closes:** #401
**Baseline test count:** 11266 (Wave 57, commit `a5523ab`) → expected **11280** (+14 net), ceiling **+15**
**HEAD at draft:** post-Wave-57 (`a5523ab`, working tree clean)

## Summary

AD-528 v1 (Wave 7) shipped `GroundTruthVerifier` (`src/probos/cognitive/ground_truth.py`) — a 4-signal scoring layer that cross-references claimed work-item completions against `runtime.work_item_store.get_booking_journal()` + `runtime.event_log.query()` and emits `VERIFICATION_PASSED` / `VERIFICATION_FAILED`. The module's own docstring contracts the gap (`ground_truth.py:1-7`):

> "Cross-references claimed task completions against `BookingJournal` entries and `event_log` audit records. Returns a confidence score and a list of signals that matched (or didn't). Read-only over existing state in v1; active rejection deferred to AD-528b."

The roadmap entry (`docs/development/roadmap.md:6514`) names AD-528b:

> "AD-528b: Ground-Truth Verification — Active Rejection & Quarantine *(Scoped, OSS, Issue #401)* — Extend observation-only ground-truth verification (AD-528 v1) with active rejection: when postcondition checks fail, automatically reject the WorkItem completion claim, revert status to in-progress, and quarantine the agent's output for review. v1 logs discrepancies but takes no corrective action."

(The roadmap "revert status to in-progress" line is structurally infeasible — `WorkItemStatus.DONE` is a TERMINAL state for the `task` work_type per `workforce.py:160` (`terminal_statuses=frozenset({"done", "failed", "cancelled"})`) and the registry rejects transitions FROM terminals at `workforce.py:272` (`if from_status in wt.terminal_statuses: return False`). v1 ships a PRE-COMMIT rejection gate (intercepts BEFORE status transitions to `done`) plus metadata-only quarantine (`work_item.metadata[<key>] = {...}` via the existing `WorkItemStore.update_work_item(work_item_id, metadata=...)` path). State-machine extension to add a `quarantined` status is deferred to AD-528b-5; reverting from `done` requires that status addition first.)

AD-528b v1 ships:

1. **`RejectionDecision`** — new frozen dataclass in `cognitive/ground_truth.py`. Fields: `verified: bool`, `score: float`, `action: str` (`"allow"` | `"reject"`), `quarantine_metadata: dict[str, Any]`, `signals: list[str]`, `booking_id: str`, `agent_id: str`, `work_item_id: str`. Mirrors `GroundTruthResult` shape (existing `ground_truth.py:23-32`).

2. **`GroundTruthRejectionGate`** — new module-level class in `cognitive/ground_truth.py` (defined AFTER `VerificationEpisodeWriter`). Accepts `verifier: GroundTruthVerifier`, `runtime: Any`, `emit_event: Any | None = None`, `metadata_key: str = "ground_truth_quarantine"` as kwargs. Public method: `async evaluate(*, booking_id, agent_id, claimed_summary, work_item_id, completed_at=None) -> RejectionDecision`. Internally: calls `verifier.verify()`; on `result.verified=True` returns `action="allow"` with empty `quarantine_metadata`; on `result.verified=False` builds quarantine metadata dict, attempts to apply via `runtime.work_item_store.update_work_item(work_item_id, metadata=merged)`, emits `VERIFICATION_REJECTED`, and emits `WORK_ITEM_QUARANTINED` only if the metadata apply succeeded.

3. **Two new EventTypes**: `VERIFICATION_REJECTED` (the gate took the rejection branch — orthogonal to existing `VERIFICATION_FAILED` which fires on score < threshold) and `WORK_ITEM_QUARANTINED` (the metadata key actually landed on the work item).

4. **`GroundTruthConfig.active_rejection_enabled: bool = False`** — Convention #14 + #3 + Wave 55 / 56 / 57 sibling pattern: default False on the transitional flag. AD-528b-1 flips default to True once AD-528b-2 (caller integration — wrap `transition_work_item(..., "done")` to consult the gate) lands.

5. **`GroundTruthConfig.quarantine_metadata_key: str = "ground_truth_quarantine"`** — operator-configurable metadata key. Mirrors `audit_persistence_filename` shape (AD-456d, `config.py:1480`).

6. **`startup/finalize.py` wiring** — single new sub-block inserted INSIDE the existing AD-528 `if config.ground_truth.enabled:` block, AFTER the `VerificationEpisodeWriter` construction and BEFORE the closing `logger.info("AD-528: ...")` line. Constructs `GroundTruthRejectionGate` only when `config.ground_truth.active_rejection_enabled and runtime.ground_truth_verifier is not None`. Sets `runtime.ground_truth_rejection_gate = gate` (greenfield runtime attribute). Else-branch (the existing `else: runtime.ground_truth_verifier = None ; runtime.verification_episode_writer = None` pair at `finalize.py:1395-1397`) extends to `runtime.ground_truth_rejection_gate = None`.

3 sections + Section 0 EventTypes, 4 source-edit files (`events.py`, `config.py`, `cognitive/ground_truth.py` — substantial additive content, `startup/finalize.py`), 1 new test file (14 tests).

The caller integration (wrap `transition_work_item(..., "done")` to consult the gate before allowing the transition; offer the agent a re-verification path), default-flip of `active_rejection_enabled`, Counselor / Captain alert routing on quarantine, re-verification retry workflow, status-machine extension (`quarantined` status), trust-network feedback (which is a distinct AD — AD-528c, Wave 59), and commercial overlays (compliance-grade quarantine workflows / SOX / GDPR audit-export hooks via `RejectionDecision` extension point) are pre-deferred at the prompt level to AD-528b-2 / -1 / -3 / -4 / -5 / AD-528c / -6 *(Commercial)* respectively.

## Architect calls (Decision Log)

- **DLog #1 — Mirror AD-456b/c/d transitional-flag posture exactly.** Convention #14 + #3 + Waves 55/56/57 precedent: default-False on the new transitional flag. `egress_active_enforcement` (AD-456b), `credential_tier_enforcement` (AD-456c), `audit_persistence_enabled` (AD-456d) are the four immediate sibling patterns; `active_rejection_enabled` follows the same naming, default, comment shape, and finalize-block conditional. Forcing function: AD-528b-1 flips default to True once AD-528b-2 (caller integration) lands.

- **DLog #2 — Wave-10 reframe pre-applied: PRE-COMMIT gate, NOT post-commit revert.** Roadmap text says "revert status to in-progress" but the `task` work_type's terminal-status set (`workforce.py:160`) makes that structurally infeasible — `WorkTypeRegistry.validate_transition` (`workforce.py:268-281`) rejects ALL transitions FROM `done`/`failed`/`cancelled`. v1 ships a PRE-COMMIT gate (caller calls `gate.evaluate(...)` BEFORE attempting `transition_work_item(..., "done")`) plus metadata-only quarantine. Adding a `quarantined` status to the `task` work_type's `valid_transitions` list would touch the BUILTIN_WORK_TYPES dict + every test that enumerates valid statuses + the `_TERMINAL_STATUSES` frozenset (`workforce.py:610`) — substantial v1 risk. State-machine extension is the most explicit deferral: AD-528b-5.

- **DLog #3 — Wave-10 reframe pre-applied: producer-only v1, NO caller integration.** AD-528 v1 (Wave 7) shipped the verifier with ZERO production callers (verified at HEAD: `grep "ground_truth_verifier\." src/` and `grep "verification_episode_writer\." src/` both return zero hits at `a5523ab`). AD-528b v1 follows the same posture — ship the rejection-gate layer, defer caller integration. Reasoning: the workforce-side wiring (consult the gate before allowing `→ done` transitions) requires either (a) a `WorkItemStore` constructor hook for the gate, OR (b) a `WorkforceSchedulingEngine`-level pre-transition callback, OR (c) a `BookingService` completion hook. All three need their own design AD — premature in v1 before any production caller of `verifier.verify()` exists. Forcing function: AD-528b-2.

- **DLog #4 — Two EventTypes, not one.** `VERIFICATION_REJECTED` (the gate took the rejection branch) is semantically distinct from `WORK_ITEM_QUARANTINED` (the quarantine metadata actually landed on the work item). The two can diverge: a missing `runtime.work_item_store` OR a missing work item OR an `update_work_item` exception means REJECTED fires but QUARANTINED does NOT. HXI dashboards / Counselor consumers / future AD-528b-3 alert paths need both signals to disambiguate "the gate decided to reject" from "the rejection successfully persisted to the work item". One event would conflate the two. Two events, two semantic levels.

- **DLog #5 — `VERIFICATION_REJECTED` is orthogonal to existing `VERIFICATION_FAILED`.** Existing `VerificationFAILED` (AD-528, `ground_truth.py:163-181`) fires whenever `result.verified is False` — score below threshold. New `VERIFICATION_REJECTED` fires only when the gate's `evaluate()` runs AND takes the rejection branch. On the rejected path, BOTH events fire (FAILED first from `verifier.verify()` inside the gate; REJECTED second from the gate). HXI / Counselor consumers can subscribe to either; FAILED tracks raw score signal, REJECTED tracks the action. Test #8 explicitly asserts both fire on the reject path; Test #9 asserts neither REJECTED nor QUARANTINED fire on the allow path (FAILED still fires because the verifier is unchanged — Test #6 asserts that).

- **DLog #6 — `metadata` field is JSON-serialised in WorkItemStore.** Verified at `workforce.py:891-895` — `_JSON_FIELDS` includes `"metadata"`, and `update_work_item` at `workforce.py:1119-1121` auto-`json.dumps` non-string values. The gate passes a dict; the store handles serialization. NOT in `_IMMUTABLE_FIELDS` (`workforce.py:898`). The merge is read-modify-write: `existing = dict(item.metadata or {}) ; existing[self._metadata_key] = quarantine_payload ; await store.update_work_item(work_item_id, metadata=existing)`. Test #11 asserts existing metadata keys survive the merge.

- **DLog #7 — `_apply_quarantine` is log-and-degrade tier (3-tier rule, tier 2).** `update_work_item` failure must NOT propagate up to the caller of `evaluate()` — the rejection decision (the cognitive fact) is already computed and the `VERIFICATION_REJECTED` event is ALREADY emitted before `_apply_quarantine` runs; the metadata-apply is a downstream side-effect for which a failure is non-critical. Mirrors `verifier._fetch_journal` (`ground_truth.py:120-128`) and `verifier._has_recent_event` (`ground_truth.py:144-152`) exactly — same module's existing log-and-degrade shape. Test #14 forces an exception via `update_work_item = AsyncMock(side_effect=Exception(...))` and asserts the warning log + `RejectionDecision` still returns with `action="reject"`.

- **DLog #8 — Gate emits its OWN events; does NOT swap the verifier's emit hook.** The gate accepts its own `emit_event` kwarg (mirrors verifier's shape). Both share `runtime.emit_event` in production wiring. The verifier's PASSED/FAILED emit is unchanged — the gate adds REJECTED/QUARANTINED on top. If the gate were constructed with `emit_event=None`, REJECTED and QUARANTINED would be silent (no emit) but the gate's behaviour (decision + metadata apply) would still execute. Test #12 locks the no-emit-hook silent path.

- **DLog #9 — `RejectionDecision` is frozen dataclass, immutable.** Mirrors `GroundTruthResult` shape exactly (`ground_truth.py:23-32` — `@dataclass(frozen=True)`). Frozen because consumers (HXI / Counselor / future AD-528b-2 caller wiring) need a value-type they can pass around without defensive-copy. Field order: required-no-default fields first (`verified`, `score`, `action`), then defaulted fields (`quarantine_metadata: dict[str, Any] = field(default_factory=dict)`, `signals: list[str] = field(default_factory=list)`, `booking_id: str = ""`, `agent_id: str = ""`, `work_item_id: str = ""`). Frozen + defaulted-after-required + `field(default_factory=...)` for mutable types — copilot-instructions Engineering Principles compliance.

- **DLog #10 — `quarantine_metadata` payload schema.** Frozen contract: `{"score": float, "signals": list[str], "rejected_at": float (epoch), "reason": "ground_truth_score_below_threshold", "booking_id": str, "agent_id": str}`. The fields are READ-MODIFY-WRITE merged into `work_item.metadata[self._metadata_key]` — they don't replace the whole metadata dict. Test #10 locks the payload shape; Test #11 locks the merge semantics.

- **DLog #11 — `runtime.ground_truth_rejection_gate` is a NEW public attribute.** Convention #1 (Wave 5): public attribute, no underscore. Greenfield — verified zero hits at HEAD `a5523ab`. AD-528b-2 caller integration (deferred) will read `runtime.ground_truth_rejection_gate` to call `await gate.evaluate(...)` before allowing `→ done` transitions. v1 sets the attribute even though no caller reads it yet — same posture as AD-528 setting `runtime.ground_truth_verifier` (Wave 7) before any production caller existed.

- **DLog #12 — `metadata_key` configurable, default `"ground_truth_quarantine"`.** Mirrors `audit_persistence_filename` shape (AD-456d). Operators with multiple verification regimes (AD-451 ReconciliationEscalator may eventually need its own quarantine key) need key-level control without overriding `metadata` itself. Test #4 locks the default; Test #11 verifies the merged-metadata uses the configured key.

- **DLog #13 — Gate construction is conditional on `verifier is not None`.** finalize.py: `if config.ground_truth.active_rejection_enabled and runtime.ground_truth_verifier is not None:`. If the verifier failed to construct (somehow) but the flag was True, gate construction must NOT crash the boot. AD-528 finalize block already gates verifier construction on `config.ground_truth.enabled` — but the rejection gate has TWO preconditions (its own flag AND a verifier). The boolean conjunction is the safe shape. Test #5 (finalize) verifies gate=None when `enabled=False` even with `active_rejection_enabled=True` (verifier is None → gate is None).

- **DLog #14 — `dataclass` field-default-factory rule.** `RejectionDecision.quarantine_metadata: dict[str, Any] = field(default_factory=dict)` — NOT bare `= {}`. Standard Python footgun: bare mutable default is shared across instances. Same rule as Pydantic `Field(default_factory=...)` — copilot-instructions Engineering Principles "Bare mutable defaults" anti-pattern. Test #2 locks the field shape via `dataclasses.fields(RejectionDecision)` introspection.

- **DLog #15 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-57 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (22 verifying greps in the prompt's "Verified Against Codebase" table — all confirmed against HEAD `a5523ab`). Net-new symbols (10 listed: `RejectionDecision` dataclass, `GroundTruthRejectionGate` class, `GroundTruthRejectionGate.evaluate`, `GroundTruthRejectionGate._apply_quarantine`, `GroundTruthRejectionGate._emit`, `EventType.VERIFICATION_REJECTED`, `EventType.WORK_ITEM_QUARANTINED`, `GroundTruthConfig.active_rejection_enabled`, `GroundTruthConfig.quarantine_metadata_key`, `runtime.ground_truth_rejection_gate`, `tests/test_ad528b_active_rejection.py`) are intra-prompt-introduction (Sections 0 / 1 / 2a-c / 3 SEARCH/REPLACE). Same FP class as Waves 27-57.

- **DLog #16 — Test count target +14, ceiling +15.** 14 explicit tests in Section 4. The +15 ceiling allows one boundary discovery during build (Wave-30/39/41/42/53/55/56/57 precedent). If post-build delta is <+14 or >+15, hard-stop and triage before commit. Wave 57 baseline (11266) + 14 new = 11280 net target.

- **DLog #17 — Commercial-leak audit: clean.** AD-528b is OSS plumbing — a `RejectionDecision` value type + a `GroundTruthRejectionGate` class + two new EventTypes + two new Pydantic fields + a finalize sub-block. AD-528b-6 *(Commercial)* deferral entry tags compliance-grade quarantine workflows (SOX evidence chain, GDPR right-to-erasure attestation, regulatory audit-export hooks) as the extension-point seam — describes WHAT plugs in (extension point on the existing `RejectionDecision.quarantine_metadata` dict + emit-event subscription on `WORK_ITEM_QUARANTINED`), NOT business model. Pricing, customer counts, professional-services positioning, competitive analysis tables, demo scripts with sales positioning all belong in the private commercial repo entirely. v1 ships zero references to pricing, tier strategy, customer counts, or competitive positioning. Commercial-leak audit: **clean**.

- **DLog #18 — Distinct from AD-528c (Wave 59).** AD-528b is the ACTION layer (active rejection + metadata quarantine). AD-528c is the LEARNING layer (trust-network feedback — verified completions raise trust, failed verifications lower trust with graduated severity). They are sequential dependencies in the wave queue (Wave 58 → Wave 59) but architecturally distinct. v1 of AD-528b emits `VERIFICATION_REJECTED` / `WORK_ITEM_QUARANTINED` as observable signals; AD-528c (Wave 59) will subscribe to those events and feed `TrustNetwork.update(agent_id, ...)`. v1 does NOT touch `TrustNetwork`, `runtime.trust_network`, or `consensus/trust.py`. Crossing that boundary in v1 would conflate the two ADs and force a re-review pass. Test set explicitly avoids any trust-network assertions.

- **DLog #19 — No Wave-10 reframe trigger expected during build.** v1 scope is already minimal per pre-applied Wave-10 / wave-5 convention #3: pre-commit gate instead of post-commit revert (AD-528b-5); producer-only with caller integration deferred (AD-528b-2); metadata-only quarantine instead of state-machine status (AD-528b-5); default-False flag (AD-528b-1); alert routing deferred (AD-528b-3); re-verification deferred (AD-528b-4); trust-network feedback distinct (AD-528c); commercial overlays deferred (AD-528b-6). The Builder will hard-stop and surface ONLY if existing AD-528 tests REGRESS — which they should not, because every additive symbol is greenfield and the existing `GroundTruthVerifier` / `VerificationEpisodeWriter` classes are NOT modified.

- **DLog #20 — Anti-`ad-528a-style misclassification` audit.** No prior `AD-528a` artifact exists at HEAD `a5523ab` (verified: zero hits in `prompts/`, `prompts/archive/`, `DECISIONS.md`, `decisions-era-*.md`, `PROGRESS.md`, `progress-era-*.md`, `docs/development/roadmap.md` — `grep -r "AD-528a\|528a"` returns no matches). The user's anti-misclassification clause is a forward-looking constraint: this prompt MUST NOT (a) re-scope AD-528b as a sub-letter (`AD-528a-1` etc.) — it's the b-tier root; (b) bundle AD-528c trust-network feedback into this AD; (c) bundle AD-528b-2 caller integration into this AD; (d) silently introduce a new top-level AD number outside the 528-cluster naming. Single AD = single deferral root = single GH issue (#401). Audit: clean.

## Highest-risk constraints (re-read before each Section)

1. **Section 2a `RejectionDecision` field-default order.** Frozen dataclasses require defaulted fields AFTER non-defaulted fields. Order: `verified: bool` (no default), `score: float` (no default), `action: str` (no default), `quarantine_metadata: dict[str, Any] = field(default_factory=dict)`, `signals: list[str] = field(default_factory=list)`, `booking_id: str = ""`, `agent_id: str = ""`, `work_item_id: str = ""`. SEARCH locks the existing module's blank-line separator after `class VerificationEpisodeWriter:` definition close (last line of file at `ground_truth.py:244`); REPLACE appends after a blank-line separator.

2. **Section 2b `GroundTruthRejectionGate` is at MODULE level**, NOT nested inside `GroundTruthVerifier`. Module-level definition lets tests import it directly (`from probos.cognitive.ground_truth import GroundTruthRejectionGate`). SEARCH locks the trailing line of `RejectionDecision` (Section 2a's REPLACE output); REPLACE appends the new class after a blank-line separator.

3. **Section 2b `evaluate()` order of operations.** Sequence:
   ```
   result = await self._verifier.verify(booking_id=..., agent_id=..., claimed_summary=..., completed_at=...)
   if result.verified:
       return RejectionDecision(verified=True, score=result.score, action="allow",
                                signals=list(result.signals), booking_id=booking_id,
                                agent_id=agent_id, work_item_id=work_item_id)
   # rejection branch
   payload = {"score": result.score, "signals": list(result.signals),
              "rejected_at": time.time(), "reason": "ground_truth_score_below_threshold",
              "booking_id": booking_id, "agent_id": agent_id}
   self._emit(EventType.VERIFICATION_REJECTED, {**payload, "work_item_id": work_item_id})
   applied = await self._apply_quarantine(work_item_id, payload)
   if applied:
       self._emit(EventType.WORK_ITEM_QUARANTINED, {**payload, "work_item_id": work_item_id,
                                                    "metadata_key": self._metadata_key})
   return RejectionDecision(verified=False, score=result.score, action="reject",
                            quarantine_metadata=payload, signals=list(result.signals),
                            booking_id=booking_id, agent_id=agent_id, work_item_id=work_item_id)
   ```
   `VERIFICATION_REJECTED` MUST emit BEFORE `_apply_quarantine` — the rejection decision is independent of whether the metadata persists. `WORK_ITEM_QUARANTINED` MUST emit ONLY if `applied is True` — the event semantics is "metadata landed on the work item", not "the gate decided to quarantine". Test #8 / #11 / #12 lock this ordering.

4. **Section 2b `_apply_quarantine` exception handling.** `try: get_work_item ; if None return False ; merge metadata ; update_work_item ; return True` wrapped in `try/except Exception: logger.warning(..., exc_info=True) ; return False`. The except clause MUST swallow ALL exceptions — caller is `evaluate()` which has already emitted `VERIFICATION_REJECTED`; an unhandled exception there would propagate to the gate's caller (and to the future AD-528b-2 caller wiring's task), introducing an uncaught error path. The warning log is the visible failure signal. Test #14 forces an exception via `update_work_item = AsyncMock(side_effect=Exception)` and asserts the log line + `applied=False` + decision returns with `action="reject"`.

5. **Section 2b metadata merge.** `existing = dict(item.metadata or {}) ; existing[self._metadata_key] = payload ; await self._runtime.work_item_store.update_work_item(work_item_id, metadata=existing)`. The `or {}` guard handles `item.metadata = None` (the dataclass default is `field(default_factory=dict)` per `workforce.py:586`, but defensive). The `dict(...)` copy avoids mutating the work item's in-memory metadata reference. Test #11 inserts a sentinel key into existing metadata and asserts both keys present after merge.

6. **Section 2b `_emit` is NOT async.** The verifier's `_emit` (existing `ground_truth.py:163`) is synchronous — calls `self._emit_event(et, payload)` where `_emit_event` is a sync callable. Mirror exactly. The gate's `_emit` is sync; both `evaluate` and `_apply_quarantine` call it without `await`. If `_emit_event` happens to be a coroutine in some test, the call fires-and-forgets — same behaviour as the verifier (Test #7 of AD-528 verifies this for the verifier, Test #12 of AD-528b verifies for the gate).

7. **Section 0 EventType insertion site.** SEARCH locks existing `VERIFICATION_FAILED = "verification_failed"  # AD-528` (line 216); REPLACE re-emits that line plus the two new lines:
   ```python
   VERIFICATION_REJECTED = "verification_rejected"  # AD-528b
   WORK_ITEM_QUARANTINED = "work_item_quarantined"  # AD-528b
   ```
   Insertion order (FAILED → REJECTED → QUARANTINED) reflects emit-order on the rejection path: FAILED fires inside `verifier.verify()`, REJECTED fires when the gate decides, QUARANTINED fires after metadata lands. Adjacency to AD-528 events keeps the cluster coherent.

8. **Section 1 config field append site.** SEARCH locks the existing `GroundTruthConfig` body (5 fields — `enabled`, `threshold`, `event_window_seconds`, `write_episode`, plus class docstring), `config.py:1292-1300`. REPLACE re-emits the existing fields verbatim plus the two new fields appended at the end. Field order: `active_rejection_enabled` BEFORE `quarantine_metadata_key` (transitional flag first, configurable name second — same shape as AD-456d).

9. **Section 3 finalize wiring inside existing AD-528 if-block.** SEARCH locks the existing `if config.ground_truth.write_episode:` ... `else: runtime.verification_episode_writer = None` block (`finalize.py:1383-1389`) plus the trailing `logger.info("AD-528: GroundTruthVerifier wired ...")` block (`finalize.py:1390-1394`). REPLACE re-emits the existing content verbatim PLUS a new sub-block after the `verification_episode_writer` assignment and BEFORE the `logger.info(...)`:
   ```python
   if config.ground_truth.active_rejection_enabled and runtime.ground_truth_verifier is not None:
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
   ```
   The OUTER `else` branch (`finalize.py:1395-1397`) ALSO extends — when `config.ground_truth.enabled` is False, `runtime.ground_truth_rejection_gate = None` joins `verifier = None` and `episode_writer = None` in the existing else.

10. **Section 4 test isolation.** Tests use `SimpleNamespace` runtimes with `AsyncMock` stand-ins for `work_item_store` (mirrors AD-528 test pattern at `test_ad528_ground_truth.py:33-46`). No `tmp_path` needed — no SQLite files. No tests share gate / verifier instances — each test calls `_make_gate()` fresh. pytest-xdist parallel runs are safe (pure-Python, no I/O).

11. **Test #9 (`test_evaluate_does_not_emit_rejected_or_quarantined_on_allow`) negative-emit assertion.** Test runs the allow path, captures all `emit_event` calls, asserts none of them carry `VERIFICATION_REJECTED` or `WORK_ITEM_QUARANTINED`. The verifier's `VERIFICATION_PASSED` MAY fire (from `verifier.verify()` inside `evaluate`) — that's expected; the assertion is specifically against the gate's emit shapes. Use `[c.args[0] for c in emit.call_args_list]` to enumerate event types.

12. **Do NOT modify `GroundTruthVerifier`.** Existing 11 tests in `test_ad528_ground_truth.py::TestVerifier` (lines 73-218) call `GroundTruthVerifier(runtime=..., emit_event=..., threshold=...)` and assert specific score / signal / event behaviour. The new gate WRAPS the verifier — does not modify it. Test #6 explicitly asserts the verifier's `_emit_event` is still called once (verifier's existing PASSED/FAILED emit is preserved).

13. **Do NOT modify `VerificationEpisodeWriter`.** Existing 3 tests (`test_episode_writer_*`, lines 222-263) assert episode-store persistence semantics. The episode writer is orthogonal to active rejection — a future AD-528b-N may add episode records for rejection events, but v1 does not.

14. **Do NOT modify `_TERMINAL_STATUSES` (`workforce.py:610`) or `BUILTIN_WORK_TYPES` (`workforce.py:140`).** State-machine extension is AD-528b-5. Touching either would break the `task` work_type's transition contract and force a re-review of every test that enumerates valid statuses.

15. **Do NOT modify `WorkItemStore.update_work_item` (`workforce.py:1108-1138`).** The merge happens IN THE GATE before calling update_work_item — the store sees a complete `metadata` dict. v1 does NOT add a partial-update mode to the store.

16. **Do NOT add a NEW pool, agent, or module beyond the 1 new test file.** No new EventType beyond the two listed. No new Pydantic config class — fields append to existing `GroundTruthConfig`. No new file beyond `tests/test_ad528b_active_rejection.py`.

17. **Do NOT couple to `TrustNetwork` / `runtime.trust_network` / `consensus/trust.py`.** AD-528c (Wave 59) territory. v1 emits `VERIFICATION_REJECTED` / `WORK_ITEM_QUARANTINED` as observable signals; AD-528c subscribes. v1 has zero `import probos.consensus.trust` and zero `runtime.trust_network` references.

18. **Do NOT couple to `ReconciliationEscalator` (AD-451).** AD-451 covers verifier-vs-verifier disagreement; AD-528 covers did-it-happen-at-all; AD-528b covers what-do-we-do-when-it-didn't-happen. The three are orthogonal at v1. Future AD-528b-N may emit a `VerificationRejectionResult` that ReconciliationEscalator can ingest as a third opinion — v1 does not wire that.

## Phantom-API pre-check result

Auto-run blocked by pre-existing script parser error (DLog #15, recurring from Waves 52-57). Manual verify-first pass: 22 verifying greps in the prompt's "Verified Against Codebase" table all hit at HEAD `a5523ab`. Net-new symbols (10 listed in DLog #15) are intra-prompt-introduction (Sections 0 / 1 / 2a-c / 3 SEARCH/REPLACE). Same FP class as Waves 27-57.

## Pre-flight gate

```powershell
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected baseline: **11266 passed**.

## Build groups

Single group, sequential:

1. Section 0 — `events.py` adds `VERIFICATION_REJECTED` + `WORK_ITEM_QUARANTINED`
2. Section 1 — `config.py` `GroundTruthConfig` adds `active_rejection_enabled: bool = False` + `quarantine_metadata_key: str = "ground_truth_quarantine"`
3. Section 2a — `cognitive/ground_truth.py` adds `RejectionDecision` frozen dataclass at module level
4. Section 2b — `cognitive/ground_truth.py` adds `GroundTruthRejectionGate` class at module level (init, evaluate, _apply_quarantine, _emit)
5. Section 3 — `startup/finalize.py` extends existing AD-528 if-block with rejection-gate sub-block; extends outer else-branch
6. Section 4 — `tests/test_ad528b_active_rejection.py` NEW (14 tests)
7. Run focused gate: `pytest tests/test_ad528b_active_rejection.py tests/test_ad528_ground_truth.py -v -n 0`
8. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`

## Hard-stop conditions

- An existing test in `tests/test_ad528_ground_truth.py` (14 tests) regresses after Section 2 lands. The change is strictly additive — new symbols defined AFTER existing classes; no existing class body modified. If a regression appears, most likely cause is Section 2a SEARCH/REPLACE landed inside `VerificationEpisodeWriter` body instead of after it (verify the SEARCH anchor is the trailing `return False` of `write()`).

- A test in `tests/test_finalize*.py` regresses (if any exists for AD-528 wiring). Section 3 SEARCH locks the existing AD-528 if-block; REPLACE re-emits the existing content verbatim plus the additive sub-block. If the existing AD-528 emit-order changes (e.g. `runtime.verification_episode_writer` assignment moves), the finalize test would fail. Verify the SEARCH anchor preserves the exact existing content.

- An existing test in `tests/test_ad456*.py` regresses. Orthogonal — no symbol overlap with AD-528b. If a regression appears, the failure is most likely in `events.py` (Section 0 — verify `VERIFICATION_FAILED` is preserved AND the two new values are unique).

- Pydantic config validation failure at startup (every test would fail). Section 1 SEARCH locks the existing `GroundTruthConfig` body; REPLACE re-emits the existing 4 fields unchanged plus the two new fields. If the Builder accidentally overwrites an existing field's default, validation breaks. Verify that `enabled: bool = True`, `threshold: float = Field(default=0.75, ge=0.0, le=1.0)`, `event_window_seconds: float = Field(default=600.0, ge=10.0)`, `write_episode: bool = True` all survive the REPLACE.

- A test fails under `-n 8` parallel xdist but passes serial (`-n 0`). Standard triage per `.github/copilot-instructions.md` — re-run failing file at `-n 0` first. Section 4 tests use SimpleNamespace + AsyncMock (no I/O, no shared state) — no file races. If parallel-only failures appear, mark `xfail(reason="env-dependent under xdist; AD-682")` rather than expanding the assertion window.

- Phantom-API pre-check script remains broken (DLog #15) — non-blocker for THIS wave; cleanup AD remains pending.

- Test count delta < +14 OR > +15 — investigate before commit (drift signal).

- Test #11 metadata-merge race (`test_evaluate_preserves_existing_work_item_metadata`). If the test fails with the existing key missing from the post-merge dict, most likely cause is the gate using `{self._metadata_key: payload}` instead of `existing[self._metadata_key] = payload` — a destructive replace instead of a merge. Verify Section 2b `_apply_quarantine` uses the read-modify-write pattern (DLog #6, risk constraint #5).

- Test #14 exception-swallowing race (`test_evaluate_handles_update_exception_log_and_degrade`). If the test fails with the exception propagating out of `evaluate()`, most likely cause is the `try/except` in `_apply_quarantine` not covering `update_work_item` OR the exception shape being raised inside `evaluate` itself rather than in the helper. Verify Section 2b `_apply_quarantine` wraps the WHOLE body (including get_work_item, dict merge, update_work_item) in the try block, NOT just the update.

- An attempt to import `probos.consensus.trust` or reference `runtime.trust_network` slips into Section 2 (DLog #18 / risk constraint #17). v1 hard-boundary: zero trust-network coupling. AD-528c is Wave 59.

## Tracker updates (post-build, single commit per ask)

- `PROGRESS.md` — prepend AD-528b CLOSED entry. (Note: AD-456c/d builders skipped this step in Waves 56/57; if precedent holds, the Captain may handle the tracker update separately. Builder should ATTEMPT the prepend; non-blocker if skipped.)
- `docs/development/roadmap.md` — flip AD-528b row to ✅ shipped under the AD-528 cluster; add deferral entries:
  - **AD-528b-1**: Default-flip of `active_rejection_enabled` to True once AD-528b-2 lands.
  - **AD-528b-2**: Caller integration — wrap `WorkItemStore.transition_work_item(..., "done")` (or equivalent BookingService completion hook) to consult `runtime.ground_truth_rejection_gate.evaluate(...)` before allowing the transition. Real producer-side wiring.
  - **AD-528b-3**: Counselor / Captain alert routing on `WORK_ITEM_QUARANTINED` (HXI surface + alert paths).
  - **AD-528b-4**: Re-verification retry workflow — agent supplies new evidence, gate re-evaluates, quarantine metadata updates with retry attempt.
  - **AD-528b-5**: State-machine extension — add `quarantined` status to `task` work_type's `valid_transitions` (and `_TERMINAL_STATUSES` audit). Enables true "revert from done to quarantined" semantics that the roadmap text envisioned.
  - **AD-528b-6** *(Commercial)*: Compliance-grade quarantine workflows / SOX evidence chain / GDPR right-to-erasure attestation / regulatory audit-export hooks — extension point on the existing `RejectionDecision.quarantine_metadata` dict + `WORK_ITEM_QUARANTINED` event subscription.
- `DECISIONS.md` — prepend AD-528b entry at top of Era V. (Same precedent caveat as PROGRESS.md.)

## Issues to close

GitHub MCP `issue_write` close on **#401** (expect EMU 403 same as Waves 31-57; Captain closes manually).

## Commit message

`AD-528b: Ground-Truth active rejection & metadata quarantine (GroundTruthRejectionGate + RejectionDecision) (+14 tests)`

## Concerns for orchestrator at gate_1

1. **Phantom-API pre-check script is broken** (DLog #15, recurring from Waves 52-57). Builder cannot run the standard pre-check; manual verify-first pass already done at draft (22 verifying greps). Forcing function for a tooling-hygiene-AD logged but NOT scoped into this wave.

2. **Zero production callers of `GroundTruthVerifier.verify()` AND zero callers planned for `GroundTruthRejectionGate.evaluate()` in v1** (DLog #3). The wave ships the producer-side layer with full unit-test coverage; AD-528b-2 is the explicit follow-up that wires the actual workforce-side caller. This is the same posture AD-528 v1 took (Wave 7) — verifier was wired but had no callers; AD-528b was the planned consumer. AD-528b v1 inherits the same pattern: gate wired but no callers; AD-528b-2 is the planned consumer. NOT a smell — explicit Wave-10 reframe applied at the AD-cluster level.

3. **Roadmap text "revert status to in-progress" is structurally infeasible at v1** (DLog #2). The state machine rejects transitions FROM terminal statuses (`workforce.py:272`). v1 ships PRE-COMMIT gate + metadata-only quarantine; state-machine extension to add a `quarantined` status is explicit AD-528b-5 deferral. The roadmap row will need an editorial update after this wave to reflect the actual v1 surface vs the long-term AD-528b-cluster surface. Builder NOT responsible for the editorial update — Captain handles that pass.

4. **AD-528c is the IMMEDIATELY NEXT wave (Wave 59)** and shares the same module (`cognitive/ground_truth.py`) for trust-network feedback wiring. The two ADs MUST stay distinct — v1 of AD-528b has zero `import probos.consensus.trust` and zero `runtime.trust_network` references (DLog #18, risk constraint #17). If the Builder accidentally couples them, the orthogonality breaks and Wave 59's review pass becomes a re-pass. Verify Section 2 imports are limited to: `EventType`, `GroundTruthVerifier` / `GroundTruthResult` (in-module references), `time`, `logging`, `dataclasses`, `typing`. NO trust imports.
