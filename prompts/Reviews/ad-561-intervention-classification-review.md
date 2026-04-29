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
