# WAVE 59 DISPATCH — AD-528c v1 Ground-Truth Trust-Network Feedback

**Wave id:** 59
**Single AD:** AD-528c
**Closes:** #402
**Baseline test count:** 11280 (Wave 58, commit `6b24d75`) → expected **11292** (+12 net), ceiling **+13**
**HEAD at draft:** post-Wave-58 (`6b24d75`, working tree clean)

## Summary

AD-528 v1 (Wave 7, commit `259dc1b`) shipped `GroundTruthVerifier` — a 4-signal scoring layer that emits `VERIFICATION_PASSED` / `VERIFICATION_FAILED`. AD-528b v1 (Wave 58, commit `06ce3ab`) added `GroundTruthRejectionGate` that emits `VERIFICATION_REJECTED` + `WORK_ITEM_QUARANTINED` on the rejection branch. Neither AD touches `runtime.trust_network`. AD-528b's class docstring contracts the boundary explicitly (`ground_truth.py:299-300`):

> "Trust-network feedback (raise/lower trust on PASSED/FAILED/REJECTED) is a distinct AD — AD-528c (Wave 59). v1 of this class has zero coupling to ``runtime.trust_network`` or ``probos.consensus.trust``."

GH issue #402:

> "Feed verification outcomes back into TrustNetwork via `record_outcome()`. Discrepancy between agent claim and verification adjusts trust scores. v1 intentionally kept trust scoring out of the loop during system stabilization."

AD-528c v1 closes the learning-loop gap. It's a pure event-listener + sidecar — no modification of `GroundTruthVerifier`, `GroundTruthRejectionGate`, `TrustNetwork`, or `consensus/trust.py`. It subscribes to verification events via the existing `runtime.add_event_listener(fn, event_types=...)` API (`runtime.py:683-687`) and calls the existing public `runtime.trust_network.record_outcome(agent_id, success, weight, intent_type, episode_id, verifier_id, source)` API (`consensus/trust.py:208-216`). `record_outcome` internally stores raw `(alpha, beta)` Beta-distribution parameters per **ProbOS principle 3** — AD-528c does not bypass that contract; it only invokes the public method.

AD-528c v1 ships:

1. **`GroundTruthTrustFeedback`** — new module-level class in `cognitive/ground_truth.py` (defined AFTER `GroundTruthRejectionGate`). Constructor: `__init__(self, *, runtime: Any, success_weight: float = 1.0, failure_weight: float = 0.5) -> None`. Public method: sync `on_event(event: dict[str, Any]) -> None` — the listener callback registered via `runtime.add_event_listener`.

2. **Listener semantics (v1)** — consumes `VERIFICATION_PASSED` and `VERIFICATION_FAILED` only. `VERIFICATION_REJECTED` is **NOT** consumed in v1: every REJECTED co-fires with a FAILED inside `verifier.verify()` (verified at `ground_truth.py:163-181` — the verifier emits PASSED/FAILED unconditionally, and `GroundTruthRejectionGate.evaluate` calls `verifier.verify()` internally before its own REJECTED emit). Distinct REJECTED-aware weighting (escalate negative weight when the gate engaged) is deferred to AD-528c-1.

3. **Outcome mapping** — `PASSED → record_outcome(success=True, weight=success_weight)`; `FAILED → record_outcome(success=False, weight=failure_weight)`. Default weights: success=1.0 (full positive update), failure=0.5 (partial negative update). Asymmetric defaults reflect that "verifier scored low" is a softer signal than "outcome confirmed" — AD-558's progressive dampening + cascade breaker provide additional safety on top.

4. **`GroundTruthConfig.trust_feedback_enabled: bool = False`** — Convention #14 + #3 + Wave 55-58 sibling pattern: default False on the transitional flag. AD-528c-1 flips default to True after a fleet rehearsal confirms no false-positive trust drops.

5. **`GroundTruthConfig.trust_feedback_success_weight: float = Field(default=1.0, ge=0.0)`** — operator-tunable success update magnitude.

6. **`GroundTruthConfig.trust_feedback_failure_weight: float = Field(default=0.5, ge=0.0)`** — operator-tunable failure update magnitude.

7. **`startup/finalize.py` wiring** — single new sub-block inserted INSIDE the existing AD-528 `if config.ground_truth.enabled:` block, AFTER the AD-528b rejection-gate sub-block (`finalize.py:1390-1410`) and BEFORE the closing `logger.info("AD-528: ...")` line (`finalize.py:1411-1415`). Constructs `GroundTruthTrustFeedback` only when `config.ground_truth.trust_feedback_enabled and runtime.trust_network is not None`. Registers the listener via `runtime.add_event_listener(feedback.on_event, event_types=[VERIFICATION_PASSED.value, VERIFICATION_FAILED.value])`. Sets `runtime.ground_truth_trust_feedback = feedback` (greenfield runtime attribute). The OUTER else-branch (`finalize.py:1416-1419`) extends to set `runtime.ground_truth_trust_feedback = None`.

8. **No new EventType.** v1 reuses existing `VERIFICATION_PASSED` (line 215, AD-528) and `VERIFICATION_FAILED` (line 216, AD-528). No new enum value.

9. **No new file beyond `tests/test_ad528c_trust_feedback.py`** (12 tests).

3 sections + 1 new test file, 3 source-edit files (`config.py`, `cognitive/ground_truth.py` — additive only, `startup/finalize.py`).

The default-flip of `trust_feedback_enabled`, REJECTED-aware weighting (escalate negative weight on rejection-gate-engaged path), Counselor / Captain alert routing on trust-floor hits triggered by ground-truth feedback, AD-558 cascade-breaker integration audit (verify ground-truth feedback respects existing dampening + floor + cascade — should "just work" because feedback uses the public `record_outcome` API), HXI dashboard surface for "trust impact attributed to ground-truth verification", and commercial overlays are pre-deferred at the prompt level to AD-528c-1 / -2 / -3 / -4 / -5 / -6 *(Commercial)* respectively.

## Architect calls (Decision Log)

- **DLog #1 — Mirror AD-528b's transitional-flag posture exactly.** Convention #14 + #3 + Waves 55/56/57/58 precedent: default False on the new `trust_feedback_enabled` flag. Config field naming + default + comment shape + finalize-block conditional all mirror AD-528b's `active_rejection_enabled` (one wave prior, same module). Forcing function: AD-528c-1 flips default True after fleet rehearsal.

- **DLog #2 — Listen to PASSED + FAILED only; SKIP REJECTED in v1.** Every `EventType.VERIFICATION_REJECTED` co-fires with a `EventType.VERIFICATION_FAILED` because `GroundTruthRejectionGate.evaluate` (`ground_truth.py:282-322`) internally calls `await self._verifier.verify(...)` — the verifier's `_emit` (`ground_truth.py:163-181`) fires `VERIFICATION_PASSED` or `VERIFICATION_FAILED` UNCONDITIONALLY, before the gate's own emit logic runs. If AD-528c v1 listened to all three event types, every rejection-gate-driven failure would update `record_outcome(success=False)` TWICE — once on FAILED and once on REJECTED. Distinct REJECTED-aware weighting (e.g. "REJECTED is a stronger signal because the gate took action; apply weight 1.0 instead of 0.5") is a real follow-up but requires the v1 listener to deduplicate or the weighting model to be explicitly cumulative. Wave-10 simplification: ship the no-double-counting version; defer REJECTED-aware weighting to AD-528c-1. Test #7 explicitly asserts `on_event(REJECTED)` is a no-op.

- **DLog #3 — Wave-10 reframe pre-applied: producer-only v1 (the listener IS the integration).** AD-528 v1 (Wave 7) and AD-528b v1 (Wave 58) shipped producer-only — no production callers of `verifier.verify()` or `gate.evaluate()` exist at HEAD `6b24d75`. AD-528c v1 is DIFFERENT — the listener IS the consumer integration, because it consumes the events the existing producers ALREADY emit. The moment AD-528 finalize wiring landed (Wave 7), `runtime.emit_event(VERIFICATION_PASSED, ...)` and `runtime.emit_event(VERIFICATION_FAILED, ...)` started firing whenever something calls `verifier.verify()`. AD-528c v1 simply subscribes. The catch: AD-528 has zero production callers of `verify()` either, so in practice no events fire today. AD-528c v1 ships the listener + wiring + 12 unit tests; the listener will become observably active once AD-528b-2 (caller integration of the rejection gate, deferred from Wave 58) lands. Until then: feedback is a no-op in production but fully unit-tested.

- **DLog #4 — `GroundTruthTrustFeedback.on_event` is sync, not async.** The runtime's `_emit_event_local` (`runtime.py:807-815`) supports both: `if asyncio.iscoroutinefunction(fn): asyncio.create_task(fn(event)) else: fn(event)`. Sync is preferred for trust-feedback because the call inside (`tn.record_outcome`) is itself sync (`consensus/trust.py:208`). Using sync avoids the create_task path — fewer fire-and-forget tasks, no GC risk. Test #11 explicitly asserts `inspect.iscoroutinefunction(feedback.on_event) is False`.

- **DLog #5 — `record_outcome` kwargs locked: intent_type, episode_id, verifier_id, source.** The public signature (`consensus/trust.py:208-216`) is `record_outcome(self, agent_id, success, weight=1.0, intent_type="", episode_id="", verifier_id="", source="verification")`. AD-528c v1 sets:
  - `intent_type="ground_truth_verification"` — matches AD-528 module domain.
  - `episode_id=str(data.get("booking_id", ""))` — links the trust update back to the verification booking.
  - `verifier_id="ground_truth"` — module-level constant, not a per-agent value (the verifier is a service, not an agent).
  - `source="ground_truth_verification"` — distinguishes from `source="verification"` (the existing default used by `runtime.py:1995-2008` consensus path).
  Test #11 locks all four kwargs.

- **DLog #6 — ProbOS principle 3 compliance: raw (alpha, beta), not derived means.** `TrustNetwork.record_outcome` internally mutates `record.alpha += effective_weight` (success path) or `record.beta += effective_weight` (failure path) — verified at `consensus/trust.py:306-308`. The Beta(alpha, beta) parameters are stored raw in `TrustRecord` (`consensus/trust.py:42-43`) and persisted raw to SQLite (`consensus/trust.py:553-555` — `INSERT INTO trust_scores (agent_id, alpha, beta, updated)`). AD-528c v1 invokes only the public `record_outcome` method — it does NOT bypass the contract by writing derived `score = alpha/(alpha+beta)` values, does NOT skip dampening (which `record_outcome` applies internally per AD-558), and does NOT touch `record.alpha` / `record.beta` directly. Compliance is structural (the public API enforces it); test #12 verifies behaviour by asserting `mock_trust_network.record_outcome.assert_called_once_with(...)` rather than asserting raw alpha/beta values (which are TrustNetwork's internal concern).

- **DLog #7 — `on_event` is tier-2 log-and-degrade.** A `record_outcome` failure must NOT propagate up — the listener is invoked from `runtime._emit_event_local` (`runtime.py:801-815`) which already wraps listener calls in `try/except: logger.debug(...)`. But debug-level swallowing is too quiet for trust-system failures; AD-528c v1's `on_event` adds an INNER `try/except: logger.warning(..., exc_info=True)` around the `record_outcome` call so a TrustNetwork-side bug (e.g. dampening config mis-init) surfaces as a WARNING with `exc_info=True`, while still preventing propagation to the runtime emit path. Test #10 forces an exception via `record_outcome.side_effect = Exception(...)` and asserts the WARNING log + on_event still returns None.

- **DLog #8 — Empty `agent_id` is a no-op.** `record_outcome` accepts an empty string and would call `get_or_create("")` — creating a phantom trust record under empty-string agent_id, polluting `TrustNetwork._records`. v1's `on_event` short-circuits on `not agent_id`. Test #8 explicitly asserts an empty-agent-id event triggers zero `record_outcome` calls.

- **DLog #9 — Missing `runtime.trust_network` is a no-op.** AD-528 / 528b finalize blocks pre-set `runtime.trust_network` in `__init__` (verified at `runtime.py:335`), but the listener must defensively handle the case where `trust_network` is None (test rigs, partial-init scenarios). v1's `on_event` short-circuits on `tn is None`. Test #9 explicitly asserts a missing-trust-network runtime triggers zero `record_outcome` calls.

- **DLog #10 — `runtime.ground_truth_trust_feedback` is a NEW public attribute.** Convention #1 (Wave 5): public attribute, no underscore. Greenfield — verified zero hits at HEAD `6b24d75` (`grep_search` for `ground_truth_trust_feedback|GroundTruthTrustFeedback|trust_feedback_enabled|trust_feedback_success_weight` returns zero matches). v1 sets the attribute even though no production code reads it — same posture as AD-528b setting `runtime.ground_truth_rejection_gate` (Wave 58) before any production caller existed. Future AD-528c-N may read this attribute to introspect feedback statistics.

- **DLog #11 — Listener registration uses string event-type names, not enum values.** `runtime.add_event_listener` (`runtime.py:683-687`) signature: `event_types: Iterable[str] | None = None`. The internal `type_filter` is a `frozenset[str]` (`runtime.py:692`). Pass `[EventType.VERIFICATION_PASSED.value, EventType.VERIFICATION_FAILED.value]` — the `.value` converts `EventType.VERIFICATION_PASSED` → `"verification_passed"`. Test #5 (PASSED dispatch) and Test #6 (FAILED dispatch) both construct events with `{"type": "verification_passed", ...}` and `{"type": "verification_failed", ...}` literal strings, mirroring `runtime._emit_event` event payload shape (`runtime.py:786-790`).

- **DLog #12 — Event payload shape: `{"type": str, "data": dict, "timestamp": float}`.** Verified at `runtime.py:786-790`: when the runtime emits a typed event, it constructs `{"type": event_type.value, "data": data or {}, "timestamp": time.time()}`. The listener receives this dict; `on_event` reads `event.get("type", "")` for routing and `event.get("data", {}) or {}` for the data payload (defensive `or {}` because `data` might be `None`). Then it reads `data.get("agent_id", "")` and `data.get("booking_id", "")` — keys verified against `GroundTruthVerifier._emit` (`ground_truth.py:163-181`) which builds `{"verified": ..., "score": ..., "signals": ..., "booking_id": ..., "agent_id": ..., "completed_at": ...}`.

- **DLog #13 — `record_outcome` weight is a float, not int.** `weight: float = 1.0` per `consensus/trust.py:212`. `success_weight: float = 1.0` and `failure_weight: float = 0.5` defaults match the existing public defaults in spirit (success=full, failure=partial) without breaking the `weight: float` contract. Pydantic validators on the new config fields use `Field(default=..., ge=0.0)` to enforce non-negative.

- **DLog #14 — Phantom-API pre-check status.** Same recurring blocker as Waves 52-58 — `scripts/phantom-api-precheck.ps1` has a pre-existing PowerShell parser error. Manual verify-first pass performed at draft (21 verifying greps in the prompt's "Verified Against Codebase" table — all confirmed against HEAD `6b24d75`). Net-new symbols (7 listed: `GroundTruthTrustFeedback` class, `GroundTruthTrustFeedback.on_event`, `GroundTruthConfig.trust_feedback_enabled`, `GroundTruthConfig.trust_feedback_success_weight`, `GroundTruthConfig.trust_feedback_failure_weight`, `runtime.ground_truth_trust_feedback`, `tests/test_ad528c_trust_feedback.py`) are intra-prompt-introduction (Sections 1 / 2 / 3 SEARCH/REPLACE). Same FP class as Waves 27-58.

- **DLog #15 — Test count target +12, ceiling +13.** 12 explicit tests in Section 4. The +13 ceiling allows one boundary discovery during build (Wave-30/39/41/42/53/55/56/57/58 precedent). If post-build delta is <+12 or >+13, hard-stop and triage before commit. Wave 58 baseline (11280) + 12 new = 11292 net target.

- **DLog #16 — Commercial-leak audit: clean.** AD-528c is OSS plumbing — a `GroundTruthTrustFeedback` listener class + 3 new Pydantic fields + a finalize sub-block + 12 tests. AD-528c-6 *(Commercial)* deferral entry tags compliance-grade trust attribution (per-jurisdiction trust-update audit trails, GDPR-compliant trust-data export hooks, regulator-facing trust-evidence chain) as the extension-point seam — describes WHAT plugs in (extension point on the existing `record_outcome` event log + `runtime.ground_truth_trust_feedback` attribute), NOT business model. Pricing, customer counts, professional-services positioning, competitive analysis tables, demo scripts with sales positioning all belong in the private commercial repo entirely. v1 ships zero references to pricing, tier strategy, customer counts, or competitive positioning. Commercial-leak audit: **clean**.

- **DLog #17 — Distinct from AD-528b (Wave 58).** AD-528b is the ACTION layer (active rejection + metadata quarantine). AD-528c is the LEARNING layer (trust-network feedback). They are sequential dependencies in the wave queue (Wave 58 → Wave 59) but architecturally distinct. AD-528c v1 emits NO events of its own — it only consumes existing AD-528 events and updates `TrustNetwork`. Test set explicitly avoids any rejection-gate or quarantine-metadata assertions.

- **DLog #18 — Distinct from AD-558 (Trust Cascade Dampening).** AD-558 is INTERNAL to `TrustNetwork.record_outcome` — progressive dampening, hard floor, cascade breaker (`consensus/trust.py:223-280`). AD-528c v1 invokes `record_outcome` and gets cascade-dampening for free (the dampening is applied by `record_outcome` regardless of caller). v1 has zero coupling to `TrustNetwork._dampening` / `_cascade` / cascade-breaker config. Test set asserts only the outward shape of `record_outcome` calls; internal dampening behaviour is AD-558 territory.

- **DLog #19 — No Wave-10 reframe trigger expected during build.** v1 scope is already minimal per pre-applied Wave-10 / wave-5 convention #3: PASSED+FAILED only (no REJECTED weighting — AD-528c-1); listener IS the integration (no additional caller-integration deferral); default-False flag (AD-528c-1); HXI dashboard deferred (AD-528c-4); audit-trail commercial overlays deferred (AD-528c-6). The Builder will hard-stop and surface ONLY if existing AD-528 / AD-528b tests REGRESS — which they should not, because every additive symbol is greenfield and the existing `GroundTruthVerifier` / `VerificationEpisodeWriter` / `GroundTruthRejectionGate` / `RejectionDecision` / `TrustNetwork` are NOT modified.

- **DLog #20 — Anti-`ad-528a-style misclassification` audit.** No prior `AD-528a` artifact exists at HEAD `6b24d75` (verified: zero hits in `prompts/`, `prompts/archive/`, `DECISIONS.md`, `decisions-era-*.md`, `PROGRESS.md`, `progress-era-*.md`, `docs/development/roadmap.md`). The user's anti-misclassification clause is a forward-looking constraint: this prompt MUST NOT (a) re-scope AD-528c as a sub-letter — it's the c-tier root; (b) bundle AD-528b-2 caller integration into this AD; (c) bundle AD-558 cascade-breaker work into this AD; (d) silently introduce a new top-level AD number outside the 528-cluster naming. Single AD = single deferral root = single GH issue (#402). Audit: clean.

## Highest-risk constraints (re-read before each Section)

1. **Section 2 `GroundTruthTrustFeedback` is at MODULE level**, NOT nested inside `GroundTruthRejectionGate`. Module-level definition lets tests import it directly (`from probos.cognitive.ground_truth import GroundTruthTrustFeedback`). SEARCH locks the trailing line of `GroundTruthRejectionGate._emit` (the existing module's last-line `logger.warning(..., exc_info=True,)` plus close paren); REPLACE re-emits that line plus appends the new class after a blank-line separator and the AD-528c section banner.

2. **Section 2 `on_event` is sync (`def`), NOT `async def`.** DLog #4. The runtime's `_emit_event_local` accepts both, but sync is preferred because `record_outcome` is sync. Test #11 asserts `inspect.iscoroutinefunction(feedback.on_event) is False`.

3. **Section 2 `on_event` order of operations.** Sequence:
   ```python
   def on_event(self, event: dict[str, Any]) -> None:
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
           return  # REJECTED and any other type -> no-op in v1
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
   The agent_id-empty guard MUST run BEFORE the trust_network None-guard (cheap dict lookup before getattr); the trust_network None-guard MUST run BEFORE the type-routing block (don't waste cycles on routing if there's no consumer). The type-routing MUST emit a `return` on the unknown-type branch — REJECTED and any future event type fall through to the `else: return` no-op. Test #7 (REJECTED no-op), Test #8 (empty agent_id no-op), Test #9 (missing trust_network no-op) lock all three guards.

4. **Section 2 `_emit` is NOT defined on `GroundTruthTrustFeedback`.** v1 emits NO events of its own — it only consumes existing AD-528 events. The class has `__init__` and `on_event`, nothing else.

5. **Section 1 config field append site.** SEARCH locks the existing `GroundTruthConfig` body (6 fields after AD-528b: `enabled`, `threshold`, `event_window_seconds`, `write_episode`, `active_rejection_enabled`, `quarantine_metadata_key`, plus the AD-528b comment block), `config.py:1292-1308`. REPLACE re-emits the existing fields verbatim plus the three new fields appended at the end. Field order: `trust_feedback_enabled` BEFORE the two weight fields (transitional flag first, configurable parameters second — same shape as AD-456d / AD-528b).

6. **Section 3 finalize wiring inside existing AD-528 if-block.** SEARCH locks the existing AD-528b sub-block (`finalize.py:1390-1410`) plus the trailing `logger.info("AD-528: GroundTruthVerifier wired ...")` block (`finalize.py:1411-1415`) plus the OUTER else-branch (`finalize.py:1416-1419`). REPLACE re-emits the existing content verbatim PLUS a new sub-block after the AD-528b `else: runtime.ground_truth_rejection_gate = None` line and BEFORE the closing `logger.info("AD-528: ...")`. The OUTER else-branch ALSO extends — when `config.ground_truth.enabled` is False, `runtime.ground_truth_trust_feedback = None` joins the existing trio.

7. **Section 3 `add_event_listener` must use `.value`, not the EventType enum.** `add_event_listener(fn, event_types=Iterable[str])`. Pass `[EventType.VERIFICATION_PASSED.value, EventType.VERIFICATION_FAILED.value]` — the strings `"verification_passed"` and `"verification_failed"`. Passing the enum directly would fail the `frozenset(str(t) for t in event_types)` conversion semantics expected by callers (the str() coercion would yield `"EventType.VERIFICATION_PASSED"` not `"verification_passed"`).

8. **Section 4 test isolation.** Tests use `SimpleNamespace` runtimes with `MagicMock` stand-ins for `trust_network` (mirrors AD-528 / AD-528b test patterns). No `tmp_path` needed — no SQLite files. No tests share feedback / runtime instances — each test calls `_make_feedback()` fresh. pytest-xdist parallel runs are safe (pure-Python, no I/O).

9. **Test #12 (`test_on_event_passes_record_outcome_kwargs_correctly`) kwargs assertion.** Use `mock_tn.record_outcome.assert_called_once_with(...)` with positional-then-kwarg shape: `("agent-7",)` positional, then `success=True, weight=1.0, intent_type="ground_truth_verification", episode_id="bk1", verifier_id="ground_truth", source="ground_truth_verification"` kwargs. Mirrors `test_evaluate_applies_quarantine_metadata_to_work_item` (AD-528b Test #10) shape. The first positional arg is `agent_id` per `record_outcome` signature; all subsequent are keyword.

10. **Test #11 (`test_on_event_is_sync_not_async`) introspection assertion.** Use `inspect.iscoroutinefunction(feedback.on_event) is False`. The runtime's `_emit_event_local` (`runtime.py:807-815`) routes sync vs async via this exact check; if v1 accidentally decorated `on_event` with `async`, the runtime would `asyncio.create_task(fn(event))` and the test would catch the regression.

11. **Do NOT modify `GroundTruthVerifier`.** Existing 11 tests in `test_ad528_ground_truth.py::TestVerifier` continue to function unchanged.

12. **Do NOT modify `GroundTruthRejectionGate`.** Existing 14 tests in `test_ad528b_active_rejection.py` continue to function unchanged.

13. **Do NOT modify `VerificationEpisodeWriter`.** Existing 3 tests in `test_ad528_ground_truth.py` continue to function unchanged.

14. **Do NOT modify `TrustNetwork` / `consensus/trust.py` / `TrustRecord`.** AD-528c v1 invokes the existing public `record_outcome` API; modifications to that surface are AD-558-cluster territory (or future AD-528c-N if a record_outcome extension becomes necessary).

15. **Do NOT add a NEW EventType.** v1 reuses existing `VERIFICATION_PASSED` and `VERIFICATION_FAILED`. No `events.py` modification.

16. **Do NOT add a NEW pool, agent, or module beyond the 1 new test file.** No new Pydantic config class — fields append to existing `GroundTruthConfig`. No new file beyond `tests/test_ad528c_trust_feedback.py`.

17. **Do NOT subscribe to `VERIFICATION_REJECTED` or `WORK_ITEM_QUARANTINED`.** DLog #2 — co-firing semantics + double-counting concern. Test #7 explicitly asserts REJECTED is a no-op. Distinct REJECTED-aware weighting deferred to AD-528c-1.

18. **Do NOT bypass `record_outcome`.** ProbOS principle 3 compliance — invoke the public method only; do NOT mutate `record.alpha` / `record.beta` directly; do NOT skip dampening; do NOT manipulate `_dampening` / `_cascade` / `_records`. DLog #6.

## Phantom-API pre-check result

Auto-run blocked by pre-existing script parser error (DLog #14, recurring from Waves 52-58). Manual verify-first pass: 21 verifying greps in the prompt's "Verified Against Codebase" table all hit at HEAD `6b24d75`. Net-new symbols (7 listed in DLog #14) are intra-prompt-introduction (Sections 1 / 2 / 3 SEARCH/REPLACE). Same FP class as Waves 27-58.

## Pre-flight gate

```powershell
git pull
d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 8 --dist=loadfile 2>&1 | Select-Object -Last 5
```

Expected baseline: **11280 passed**.

## Build groups

Single group, sequential:

1. Section 1 — `config.py` `GroundTruthConfig` adds `trust_feedback_enabled: bool = False` + `trust_feedback_success_weight: float = Field(default=1.0, ge=0.0)` + `trust_feedback_failure_weight: float = Field(default=0.5, ge=0.0)`
2. Section 2 — `cognitive/ground_truth.py` adds `GroundTruthTrustFeedback` class at module level (init + on_event)
3. Section 3 — `startup/finalize.py` extends existing AD-528 if-block with trust-feedback sub-block; extends outer else-branch
4. Section 4 — `tests/test_ad528c_trust_feedback.py` NEW (12 tests)
5. Run focused gate: `pytest tests/test_ad528c_trust_feedback.py tests/test_ad528b_active_rejection.py tests/test_ad528_ground_truth.py -v -n 0`
6. Run full gate: `pytest tests/ -q -n 8 --dist=loadfile`

## Hard-stop conditions

- An existing test in `tests/test_ad528_ground_truth.py` (14 tests) or `tests/test_ad528b_active_rejection.py` (14 tests) regresses after Section 2 lands. The change is strictly additive — new symbols defined AFTER existing classes; no existing class body modified. If a regression appears, most likely cause is Section 2 SEARCH/REPLACE landed inside `GroundTruthRejectionGate._emit` body instead of after it (verify the SEARCH anchor is the trailing `logger.warning(..., exc_info=True,)` close paren of `_emit`).

- An existing test in `tests/test_consensus_trust*.py` or any AD-558 test regresses. Orthogonal — AD-528c v1 invokes `record_outcome` via the public API but does NOT modify `TrustNetwork` source. If a regression appears, the failure is unrelated to this AD; triage via `git stash` per `.github/copilot-instructions.md` standard procedure.

- A test in `tests/test_finalize*.py` regresses (if any exists for AD-528 / AD-528b wiring). Section 3 SEARCH locks the existing AD-528 if-block including the AD-528b sub-block; REPLACE re-emits the existing content verbatim plus the additive trust-feedback sub-block. If the existing AD-528b emit-order changes (e.g. `runtime.ground_truth_rejection_gate = None` line moves), the finalize test would fail. Verify the SEARCH anchor preserves the exact existing content.

- Pydantic config validation failure at startup (every test would fail). Section 1 SEARCH locks the existing `GroundTruthConfig` body; REPLACE re-emits the existing 6 fields plus AD-528b comment block unchanged plus the three new fields. If the Builder accidentally overwrites an existing field's default, validation breaks. Verify that `enabled: bool = True`, `threshold: float = Field(default=0.75, ge=0.0, le=1.0)`, `event_window_seconds: float = Field(default=600.0, ge=10.0)`, `write_episode: bool = True`, `active_rejection_enabled: bool = False`, `quarantine_metadata_key: str = "ground_truth_quarantine"` all survive the REPLACE.

- A test fails under `-n 8` parallel xdist but passes serial (`-n 0`). Standard triage per `.github/copilot-instructions.md` — re-run failing file at `-n 0` first. Section 4 tests use SimpleNamespace + MagicMock (no I/O, no shared state) — no file races. If parallel-only failures appear, mark `xfail(reason="env-dependent under xdist; AD-682")` rather than expanding the assertion window.

- Phantom-API pre-check script remains broken (DLog #14) — non-blocker for THIS wave; cleanup AD remains pending.

- A NEW EventType is accidentally added. Section 0 does NOT exist in this prompt — there's no event-type edit. If the Builder adds one, hard-stop and revert.
