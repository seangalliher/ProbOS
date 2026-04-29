# Review: AD-561 — Intervention Classification

**Verdict:** ⚠️ Conditional
**Headline:** Missing `Enum` import in counselor.py; missing event type definition.

## Required

1. **`Enum` not imported in counselor.py.** Prompt adds `InterventionType(str, Enum)` but [counselor.py:1](src/probos/cognitive/counselor.py#L1) does not currently import `Enum`. The prompt instructs to add `from enum import Enum` — verify the SEARCH text targets the right anchor (the existing `from dataclasses import dataclass, field` line).
2. **`EventType.COUNSELOR_INTERVENTION` does not exist.** Confirmed missing in [events.py:123](src/probos/events.py#L123) (which has `COUNSELOR_ASSESSMENT`). Add as a sibling.
3. **Defensive `hasattr` in Section 3.** Code uses `if hasattr(assessment, 'trigger')` to guard `forced_dream` / `cooldown_extension`. If `assessment` is typed (it should be), drop the guard. If untyped, add type annotations per copilot-instructions (public methods must be fully annotated).

## Recommended

1. **Silent failure audit.** `_record_intervention()` calls `_emit_event_fn` without error handling. Per Fail Fast model, wrap with try/except and log at WARNING.
2. **Test the router integration.** Section 5 adds `/interventions` endpoint; tests mock `_emit_event_fn` on the agent but skip router-level testing. Add an HTTP-style test asserting the endpoint returns a correctly shaped intervention summary.

## Nits

- `_record_intervention()` docstring missing return-type statement (`-> InterventionRecord`).
- Line 2407 in `_apply_intervention()` references `multiplier` in an f-string — verify it's in scope at that call site.

## Verified

- `_emit_event_fn` attribute at [counselor.py:517](src/probos/cognitive/counselor.py#L517).
- `_send_therapeutic_dm()` at [counselor.py:2060](src/probos/cognitive/counselor.py#L2060).
- `_apply_intervention()` at [counselor.py:2377](src/probos/cognitive/counselor.py#L2377).
- `_get_counselor_agent()` helper at [routers/counselor.py:118](src/probos/routers/counselor.py#L118).
- `COUNSELOR_ASSESSMENT` at [events.py:123](src/probos/events.py#L123).

---

## Re-review (2026-04-29, second pass)

**Verdict:** ✅ Approved (with one Recommended).

| Prior Required | Status | Evidence |
|---|---|---|
| Add `from enum import Enum` to counselor.py | ✅ Fixed | Prompt now includes the import block. |
| Add `EventType.COUNSELOR_INTERVENTION` | ✅ Fixed | Section adds SEARCH/REPLACE inserting after `COUNSELOR_ASSESSMENT` at [events.py:123](src/probos/events.py#L123). |
| Drop defensive `hasattr(assessment, 'trigger')` | ⚠️ Still present | `CounselorAssessment.trigger` is a typed field at [counselor.py:63](src/probos/cognitive/counselor.py#L63); the guard is unnecessary. Drop it OR add a one-line justification comment. Not a blocker. |

### New observations

- **Redundant `import time` instruction.** Prompt instructs to add `import time` to counselor.py, but it's already imported at [counselor.py:14](src/probos/cognitive/counselor.py#L14). Drop that step.
- **`_record_intervention()` return-type annotation** still missing from the docstring. Per copilot-instructions Public API rule, annotate `-> InterventionRecord`.
- `multiplier` variable scope at the f-string near line 2404 is fine — confirmed defined at [counselor.py:2396](src/probos/cognitive/counselor.py#L2396) (`multiplier = 2.0`).

Ready to build with the small inline cleanups.
