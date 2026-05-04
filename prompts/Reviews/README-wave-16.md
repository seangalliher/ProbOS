# Wave 16 — Pass 1 Sweep Summary

**Date:** 2026-05-03
**Sub-wave:** Single-prompt
**Inputs:** 1 architect-drafted prompt (`ad-525-creative-expression-v1.md`)
**Outputs:** 1 review file (`ad-525-creative-expression-v1-review.md`) + this sweep summary

## Verdicts

| AD | Title | Risk | Verdict | Required | Recommended | Nits |
|---|---|---|---|---|---|---|
| AD-525 | Agent Creative Expression v1 | medium | ⚠️ Conditional | 3 | 4 | 3 |

**Sweep total:** 3 Required, 4 Recommended, 3 Nits across 1 prompt.

## Convergence trend

| Wave | Pass-1 Required (sum) | Verdicts |
|---|---|---|
| Wave 5 | 22 (5 prompts) | mixed |
| Wave 6 | 18 (5 prompts) | mixed |
| Wave 7 | 11 (5 prompts) | mixed |
| Wave 8 | 19 (6 prompts) | mixed |
| Wave 9A | 2 (3 prompts) | 3/3 ✅ |
| Wave 9B | 5 (2 prompts) | mixed |
| Wave 9C | 4 (1 prompt) | ⚠️ |
| Waves 10-15 | (see archive) | converging |
| **Wave 16** | **3 (1 prompt)** | **1/1 ⚠️** |

Single-prompt wave; per-prompt Required = 3 sits comfortably below the Wave 7+ multi-prompt averages (~2-4 per prompt). No regression.

## AD-685b dispatch-time catch validation

**Validated.** AD-685b's method-call AST validator caught `runtime.crew_profile_store` → real `profile_store` per `acm.py:300` at dispatch time (commit 77788e2). This is AD-685b's first non-trivial real-world catch. The Wave 15 tooling investment is paying down dispatch-time defects mechanically, exactly as the convention #16 + #20 progression predicted.

**Caveat for AD-685c/d candidate.** AD-685b caught the typo but missed the deeper defect that `runtime.profile_store` is itself never wired in `src/probos/`. The pre-check validates "method exists on receiver class" but not "receiver attribute is assigned in startup wiring." That gap is AD-685c/d territory (or a separate hygiene candidate). Surface in Wave 16 retrospective if a second instance shows up.

## CrewProfile Big Five field verification

**Result:** Big Five fields are nested under `CrewProfile.personality: PersonalityTraits`, NOT flat on `CrewProfile`. Verified:

```
src/probos/crew_profile.py:65   openness: float = 0.5            (PersonalityTraits)
src/probos/crew_profile.py:116  class CrewProfile:
src/probos/crew_profile.py:138  personality: PersonalityTraits = field(default_factory=PersonalityTraits)
```

Real callers must pass `profile.personality.openness` not `profile.openness`. v1's generic `dict[str, float]` interface survives via `PersonalityTraits.to_dict()` (verified `crew_profile.py:86` returns the dict shape via `asdict`). Surfaced as Required #3 in the review — narrative fix only; build does not break.

Additional finding during verification: `runtime.profile_store` is referenced in `acm.py:300` only as a `hasattr` defensive guard — no startup phase actually assigns it. AD-685b caught the typo (`crew_profile_store` → `profile_store`) but the attribute is dead either way. Required #3 documents the correct adapter pattern in Dependencies + Verified footer.

## AD-526 orthogonality

**Confirmed.** AD-525 lives in `src/probos/creative/` (does NOT exist today; net-new package). AD-526 lives in `src/probos/recreation/` (4 existing files: `engine.py`, `metadata.py`, `preferences.py`, `service.py`). Zero file-name collisions. Orthogonal package paths.

## Top failure modes

1. **`RecordsStore.write_entry` write-path spec gap** (Required #1) — Builder will guess kwargs absent the explicit call-shape subsection. Highest-risk Required item; affects artifact shape on disk.
2. **`_wire_creative_expression` invocation site** (Required #2) — without explicit Section 6 instruction to add the `if await _wire_creative_expression(...)` line in the entry point, runtime attributes land as `None`. Mechanical fix.
3. **CrewProfile `runtime.profile_store` claim** (Required #3) — narrative defect; v1 build survives via generic `dict[str, float]` interface but DECISIONS.md cross-references downstream.

## Hard-stops

| # | Description | Hit? |
|---|---|---|
| 1 | Phantom API beyond 1 documented FP | No (Required #3 is footer narrative, not code-shape) |
| 2 | AD-526 file-name collision | No |
| 3 | CrewProfile Big Five field shape mismatch | **Yes — surfaced as Required #3** |
| 4 | Section 0 EventType collision | No |
| 5 | v1 scope creep | No |
| 6 | `creative/` namespace already in use | No |

Hard-stop #3 hit by dispatch definition ("surface as Required"). Surfaced; not blocking beyond Required #3.

## Stage 2 dispatch readiness

Revision pass-2 dispatchable. Architect should:

1. Apply Required #1-3 verbatim.
2. Fold Recommended #1-4 unless scope creep (judgment call: #1 is mandatory for build, #2 is convention #7 hygiene, #3 may be redundant if test 18 already targets the method, #4 is mechanical).
3. Apply Nits judgment-call (Nit #1 stale citation = should fix; Nit #2 = optional rewording; Nit #3 = optional Pydantic Literal lift).
4. Re-run AD-685b pre-check after revision.
5. Convention #12 closing self-check: `grep` the prompt for OLD names/values; expect zero hits.

Targeting 1/1 ✅ on second pass.

## Cross-links

- [`prompts/ad-525-creative-expression-v1.md`](../ad-525-creative-expression-v1.md)
- [`prompts/Reviews/ad-525-creative-expression-v1-review.md`](./ad-525-creative-expression-v1-review.md)
- [`prompts/WAVE-16-DISPATCH.md`](../WAVE-16-DISPATCH.md)
- DECISIONS.md — Wave 5/5-7/8/9 Retrospective Addenda (23 standing conventions)
- AD-685b (method-call AST validation; first real-world catch validated this wave)
