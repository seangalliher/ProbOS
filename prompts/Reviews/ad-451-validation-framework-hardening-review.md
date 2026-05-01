# Review: AD-451 — Validation Framework Hardening

**Reviewer:** Architect (verify-first review of own draft)
**Date:** 2026-05-01
**Verdict:** ⚠️ **Conditional** — `SelfVerificationHook` Protocol missing `@runtime_checkable` decorator (test #13 will TypeError); `TwoStageVerifier._MetadataCheck` nested dataclass violates the module-level convention; `TwoStageVerifier` is constructed but never wired (deliverable for the validation reconciliation path is the primary value, but the metadata stage as written has no consumer). Pre-flagged Demeter concern on `RedTeamAgent` is clean — `verify(...)` is the existing public API.

---

## Required (must fix before building)

### 1. `SelfVerificationHook` Protocol missing `@runtime_checkable` — Test #13 will TypeError

Section 2 declares:

```python
class SelfVerificationHook(Protocol):
    async def self_verify(self, intent: Any, result: Any) -> tuple[bool, str]:
        ...
```

Test #13:

> `test_self_verification_hook_protocol_shape` — `SelfVerificationHook` is a `Protocol`; a concrete implementation satisfies `isinstance` via duck typing.

`isinstance(impl, SelfVerificationHook)` against a non-`@runtime_checkable` Protocol raises `TypeError: Instance and class checks can only be used with @runtime_checkable protocols`.

Verified — every existing Protocol in `protocols.py` uses `@runtime_checkable`:

```
grep -n "@runtime_checkable" src/probos/protocols.py
  (10 matches, every Protocol decorated)
```

ProbOS convention: all Protocols meant for `isinstance` use are decorated.

**Action:** Add `@runtime_checkable` to `SelfVerificationHook`:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class SelfVerificationHook(Protocol):
    async def self_verify(self, intent: Any, result: Any) -> tuple[bool, str]:
        ...
```

### 2. `TwoStageVerifier._MetadataCheck` nested dataclass violates module-level convention

Section 1 defines `_MetadataCheck` as a class-scoped nested dataclass:

```python
class TwoStageVerifier:
    ...
    @dataclass(frozen=True)
    class _MetadataCheck:
        confidence: float
        discrepancy: str
```

Verified — this pattern does NOT exist anywhere else in `src/probos`:

```
grep -rn "^    @dataclass" src/probos/
  (no matches)
```

ProbOS convention: all dataclasses are module-level. The nested form has three concrete drawbacks:

1. **Forward references awkward:** `"TwoStageVerifier._MetadataCheck"` as a return-type string is harder to type-check than a flat reference.
2. **Test introspection harder:** importing the type for assertions requires `from probos.cognitive.validation_framework import TwoStageVerifier` then `TwoStageVerifier._MetadataCheck`. Flat would be `from probos.cognitive.validation_framework import _MetadataCheck`.
3. **Style consistency:** every other private dataclass in ProbOS is module-level with a leading underscore (e.g., `_DEFAULT_CLASSIFICATIONS` in AD-459's drafted Section 2).

**Action:** Flatten to module-level:

```python
@dataclass(frozen=True)
class _MetadataCheck:
    confidence: float
    discrepancy: str


class TwoStageVerifier:
    ...
    def _metadata_check(self, intent, claimed) -> _MetadataCheck:
        ...
```

### 3. `TwoStageVerifier` is built but never wired — deliverable scope mismatch

Section 6 finalize.py wiring instantiates `ReconciliationEscalator` only:

```python
runtime.reconciliation_escalator = ReconciliationEscalator(...)
```

`TwoStageVerifier` is exposed as a class but no production code constructs an instance. The prompt body says:

> TwoStageVerifier requires a specific red_team agent — defer instance construction to per-call sites.

But no per-call sites exist or are introduced by AD-451. Result: `TwoStageVerifier` is a dead class in v1.

This is the AD-455 v1 theater pattern from Wave 5 retrospective — ship the surface, no consumer. Two options:

- **(a)** Drop `TwoStageVerifier` from v1 and defer to AD-451b. v1 ships `ReconciliationEscalator` + `SelfVerificationHook` Protocol only. Acceptance criteria reduces to ~10 tests.
- **(b)** Wire `TwoStageVerifier` somewhere — most natural seam is inside `ReconciliationEscalator._invoke_third(...)`. Instead of calling raw `RedTeamAgent.verify(...)`, the escalator could construct a `TwoStageVerifier` per call and use the metadata-only fast-path for the third opinion.

Recommended **(b)** — ties the two-stage logic into the reconciliation flow, which is the primary deliverable. Otherwise `TwoStageVerifier` is documented/tested but not exercised in production.

### 4. `ReconciliationEscalator._invoke_third` always picks `agents[2]` — no rotation, no fallback

Section 3 line 346:

```python
agents = list(getattr(self._runtime, "red_team_agents", []) or [])
if len(agents) < 3:
    return None
third = agents[2]
```

Two issues:
- **Always picks the same agent** (index 2). If that agent is unhealthy/saturated/biased, every escalation hits the same verifier. Should pick a random non-primary, non-secondary agent.
- **`primary` and `secondary` are `VerificationResult` instances, not agents.** The escalator doesn't actually know which two agents produced the disagreement. It just picks `agents[2]` — which may be `primary` or `secondary`'s producing agent.

Both flaws make the "third opinion" potentially the same agent that produced the primary or secondary verdict.

**Action:**

```python
async def _invoke_third(
    self,
    target_agent_id: str,
    intent: "IntentMessage",
    claimed: "IntentResult",
    *,
    exclude_ids: set[str],
) -> "VerificationResult | None":
    agents = [
        a for a in (getattr(self._runtime, "red_team_agents", None) or [])
        if a.id not in exclude_ids
    ]
    if not agents:
        return None
    import random
    third = random.choice(agents)
    try:
        return await third.verify(target_agent_id, intent, claimed_result=claimed)
    except Exception:
        ...
```

The caller (the public `reconcile` method) needs to track which agent IDs produced the primary and secondary results. Either pass them as args:

```python
async def reconcile(
    self,
    *,
    target_agent_id: str,
    intent, claimed,
    primary: VerificationResult, secondary: VerificationResult,
) -> ReconciliationOutcome:
    ...
    third = await self._invoke_third(
        target_agent_id, intent, claimed,
        exclude_ids={primary.verifier_id, secondary.verifier_id},
    )
```

Verified — `VerificationResult.verifier_id` exists (`types.py:199-209`):

```
grep -n "verifier_id" src/probos/types.py
  201:    verifier_id: AgentID
```

### 5. `RedTeamAgent.verify()` signature is positional, not keyword-only

Section 1's `TwoStageVerifier.verify()` calls:

```python
live = await self._red_team.verify(
    target_agent_id=target_agent_id,
    intent=intent,
    claimed_result=claimed,
)
```

Verified `RedTeamAgent.verify` signature:

```
view src/probos/agents/red_team.py:66-71
  async def verify(
      self,
      target_agent_id: str,
      intent: IntentMessage,
      claimed_result: IntentResult,
  ) -> VerificationResult:
```

The signature is positional — Python accepts the kwargs form, so this works. ✅ But Section 3 `_invoke_third` calls:

```python
return await third.verify(
    target_agent_id=target_agent_id,
    intent=intent,
    claimed_result=claimed,
)
```

Same shape, also works. Confirming no break — flagged for clarity. The kwargs form is fine.

---

## Recommended

### 1. `_metadata_check` returns 0.95 / 0.30 / 0.0 — discrete buckets, no gradient

```python
return TwoStageVerifier._MetadataCheck(0.95, "")
```

Three discrete confidence values. A real metadata check could compute a gradient (e.g., partial-match score). v1 discrete buckets are acceptable for the smoke test, but document the simplification: "v1 metadata check is a Boolean-ish pass/error/no-result classifier; richer gradients live in AD-451b."

### 2. `min_confidence_delta = 0.20` is hardcoded threshold — ship as config

The class constant `MIN_CONFIDENCE_DELTA = 0.20` is exposed as a constructor parameter and configured via `ValidationFrameworkConfig.min_confidence_delta`. ✅ Wired.

But `metadata_threshold = 0.85` on `TwoStageVerifier` is not config-bound. Add `ValidationFrameworkConfig.metadata_threshold` (already declared in Section 5 — but `TwoStageVerifier` is not wired so the config is unused). Resolve when fixing Required #3.

### 3. Test plan — `test_two_stage_verifier_*` tests assume `TwoStageVerifier` is wired

Tests 4-7 cover `TwoStageVerifier`. If Required #3 resolves toward (a) — drop `TwoStageVerifier` from v1 — these 4 tests get deferred. Update the test count from 14 to 10 in that case.

If resolving toward (b), the tests stay. Either way, the test plan needs to reflect the v1 surface, not both.

### 4. `_emit` swallows exceptions silently — tier-3 exceptions for diagnostics

```python
def _emit(self, outcome: TwoStageOutcome) -> None:
    if not self._emit_event:
        return
    try:
        self._emit_event(...)
    except Exception:
        logger.warning("AD-451: VALIDATION_OUTCOME_VERIFIED emit failed", exc_info=True)
```

Per copilot-instructions.md three-tier exception handling: this is "log-and-degrade" (tier 2), correct for diagnostics. ✅

But the `logger.warning` doesn't include actionable context (which agent_id, which intent_id). Add the IDs to the log message so operators can correlate.

### 5. `IntentMessage`, `IntentResult` imports under `TYPE_CHECKING` — runtime usage will NameError

Section 1 line 73-75:

```python
if TYPE_CHECKING:
    from probos.agents.red_team import RedTeamAgent
    from probos.types import IntentMessage, IntentResult, VerificationResult
```

These type imports are guarded. But the code at runtime references `intent.id`:

```python
intent_id=intent.id,
```

Python doesn't need the import at runtime — `intent` is duck-typed; `.id` is accessed regardless of the import. ✅ Confirmed safe.

But `_MetadataCheck` and `ReconciliationOutcome` use string forward refs (`"IntentMessage"`, etc.) for type annotations. Should switch to `from __future__ import annotations` (already imported at line 64) — eliminates the need for string forward refs. Use `IntentMessage` directly in type annotations; Python 3.11+ defers evaluation per PEP 563.

Cosmetic. Section 1 line 64 already has `from __future__ import annotations`, so the string quotes around `"IntentMessage"`, `"IntentResult"`, `"VerificationResult"`, `"BuildSpec"` (in AD-458) are redundant. Drop the quotes.

---

## Nits

### 1. `ReconciliationOutcome.resolved` is always `True`

In every code path, `resolved=True`. The field is dead. Either drop it or document a path where `resolved=False` (e.g., third invocation also failed, deadlock).

### 2. `IntentMessage.id`, `IntentResult.error/success` — verified field-existence

```
grep -n "^\s+id:\|^\s+success:\|^\s+error:" src/probos/types.py | head -10
  58:    id: str = field(default_factory=lambda: uuid.uuid4().hex)
  69:    success: bool
  71:    error: str | None = None
```

✅ All field accesses are verified. Just flagging the verification grep for completeness; the prompt's footer should include this.

### 3. Footer line for `runtime.emit_event`

Footer says line 771; actual is 775. Off by 4. Per review-criteria #6, "approximate line numbers" are acceptable — flagging for precision.

### 4. `Section 0` event values include hardcoded "AD-451" comments

✅ Matches the existing convention. Verified at `events.py:190` (`AGENT_SELF_NAMED = "agent_self_named"  # AD-499`).

---

## Verified

### Public-attribute wiring (Wave-5 convention #1) — ✅ Applied

```
runtime.reconciliation_escalator = ReconciliationEscalator(...)  # finalize.py
```

No leading underscore. ✅

### stdlib-only persistence (Wave-5 convention #2) — ✅ Applied

No new pyproject deps. Uses `time`, `dataclasses`, `typing`, `logging` — all stdlib.

### Coordinator-then-dispatch (Wave-5 convention #3) — ✅ Applied

`SelfVerificationHook` Protocol declared without wiring (deferred to AD-451b). ✅ Coordinator-then-dispatch pattern correctly invoked. The prompt body says: "v1 callers: none — AD-451 ships the protocol; AD-451b would wire it into CognitiveAgent."

### Superset-filter discipline (Wave-5 convention #4) — ✅ Applied (N/A)

No insertion into existing flows. Additive primitives only.

### `init_<phase>` startup signatures (Wave-5 convention #5) — ✅ Applied

`startup/finalize.py` receives `runtime` directly. Verified.

### Verify-first for anchors (Wave-5 convention #6) — ✅ Applied

Every concrete claim has grep evidence in the footer:
- `RedTeamAgent.verify()` ✅ at `red_team.py:66`
- `SystemQAAgent.run_smoke_tests()` ✅ at `system_qa.py:236`
- `runtime.red_team_agents` (public, post-AD-455) ✅ at `runtime.py:246, 343`
- `runtime.emit_event` ✅ at `runtime.py:775`
- `orders: OrdersConfig` anchor ✅ at `config.py:1593`

### Section 0 EventTypes — ✅ Clean

Both new EventTypes (`VALIDATION_RECONCILIATION_REQUESTED`, `VALIDATION_OUTCOME_VERIFIED`) verified absent in events.py. No collision with other Wave 6 prompts. Section 4 anchor on `AGENT_SELF_NAMED` is correct (line 190 today).

### `RedTeamAgent.verify()` API — ✅ Existing public API

The pre-flagged dispatch concern was: "Verify whether `verify(...)` exists or needs introduction here. If it lives in red_team.py, document the seam."

Verified — `verify()` exists at `red_team.py:66`. AD-451 reads but does not modify. The AD-455b deferral note is correct: AD-455b's adversarial-dispatch design also targets `verify()`; AD-451 does not interact with that deferred work. ✅

### Distinct from `system_qa.run_smoke_tests` — ✅ Correctly orthogonal

AD-451 reconciliation is about disagreement resolution between two verifiers on the same outcome; SystemQA's smoke tests are independent verification campaigns. No overlap.

### Test plan — ⚠️ 14 tests, but Test #13 will TypeError per Required #1

After Required #1 fix (`@runtime_checkable`), Test #13 works. Test counts assume Required #3 resolution toward (b) — `TwoStageVerifier` wired into reconciliation. If toward (a), drop tests 4-7 → ~10 tests.

Boundary coverage: happy path + error/edge case + None-input. ✅

### Destructive-intent consensus rule (acceptance criterion) — ✅ Applied

> AD-451's destructive-intent rule: ReconciliationEscalator only emits diagnostic events; consensus voting is unchanged. No `requires_consensus=True` introduction.

`ReconciliationOutcome` is read-only, no state mutation. ✅

### `VerificationResult` fields — ✅ Verified

```
grep -n "class VerificationResult\|verified:\|confidence:\|discrepancy:" src/probos/types.py
  199: class VerificationResult:
  201:    verifier_id: AgentID
  205:    verified: bool
  208:    discrepancy: str = ""
  209:    confidence: float = 0.0
```

All accesses (`primary.verified`, `primary.confidence`, `primary.discrepancy`) match real fields. ✅

---

## Verdict Summary

**Five blocking issues:**
1. `SelfVerificationHook` missing `@runtime_checkable` — Test #13 TypeError.
2. `TwoStageVerifier._MetadataCheck` nested dataclass violates ProbOS convention — flatten to module-level.
3. `TwoStageVerifier` is dead code in v1 — drop or wire into ReconciliationEscalator.
4. `_invoke_third` always picks `agents[2]`, doesn't exclude primary/secondary verifiers.
5. (Lift) `RedTeamAgent.verify()` kwargs form — confirmed safe; flagged for documentation only.

**Five Recommended findings:** discrete confidence buckets, hardcoded threshold partially-wired config, test count alignment, log context, redundant string forward refs.

**Four Nits:** dead `resolved` field, missing field-grep in footer, line number drift, Section 0 comment style.

**Wave-5 conventions:** all 6 applied with appropriate scoping. ✅

**Build-readiness after fix:** ~30 minutes architect time. Required #2-4 are interconnected (TwoStageVerifier scope decision affects test plan + finalize wiring). Required #1 is one-line.

**Highest-risk Wave 6 prompt by blast radius (cross-cuts consensus paths and destructive-intent gating).** Recommend the second-pass review explicitly verify the Required #3 resolution doesn't introduce new theater.
