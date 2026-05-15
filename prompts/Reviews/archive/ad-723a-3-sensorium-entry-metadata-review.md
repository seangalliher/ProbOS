# Review: AD-723a-3 — `SensoriumEntry` gains `injection_zone` + `wrapper` metadata
**Verdict:** ✅ Approved
**Pure additive frozen-dataclass extension; defaulted fields appended at end; backward-compatible with all 21 existing registry entries.**

## Required (must fix before building)

(none)

## Recommended

1. **"Ship ahead of trigger" justification is sound but should be sharper.**
   Dispatch reminder says `_DM_SELF_WRAPPED_KEYS` has 2 entries; forcing-function trigger is 3. The Solution Overview justifies: "Other DM-tagged entries (`_sensorium_temporal_context`, `_sensorium_working_memory`, `_sensorium_self_recognition`) have hand-rolled DM-side framing markers in `_build_user_message`." That's the trigger — 3 KNOWN entries waiting for migration is already 3+ pending consumers, even if the tuple itself only enumerates 2. **Rewrite the trigger statement in the AD's "Forward markers" section to say "Trigger met: 2 enumerated + 3 hand-rolled pending = 5 consumers needing zone/wrapper metadata."** Eliminates the apparent contradiction reviewers will flag.

2. **`wrapper` typed as `object | None` justification.** The docstring says: "Typed as `object | None` instead of `Callable[[str], str] | None` so the frozen dataclass remains hashable under all Python versions (some interpreters trip on the bound-method-vs-function hash divergence under `frozen=True`)." This claim is unsubstantiated — `Callable` is a Protocol-shaped type from `typing`; `frozen=True` dataclasses with `Callable` fields ARE hashable on CPython 3.10+ (the field's hashability depends on the value, not the type annotation). The dispatch's wave-specific reminders say "Reviewer should NOT flag this as weak typing — frozen-dataclass + `Callable` interactions across Python versions are unreliable." This is folkloric — the real reason is likely "Pydantic v2 / mypy strict / forward-ref interplay with `Callable` in frozen `@dataclass` is fragile." Either substantiate with a specific Python version where it breaks OR rephrase the docstring to "Typed as `object | None` to avoid forward-reference resolution complexity at module import (a `Callable[[str], str]` annotation would require `from __future__ import annotations` or a string literal; `object` sidesteps both)." Reviewer accepts the choice; rationale needs precision.

3. **Section 2 dispatcher insertion point is "Builder reads the function and picks the matching line."** That's correct but vague. Add a specific anchor: "Insert AFTER the line `result = await method(self, runtime, ...)` (or equivalent — Builder greps the actual awaited-call line) AND BEFORE any `merged[entry.output_key] = result` assignment." A concrete anchor lets Builder use single `replace_string_in_file`.

4. **`callable(entry.wrapper)` runtime check is the real type gate.** Acknowledged in docstring. Good. Optional improvement: tighten to `inspect.isfunction(entry.wrapper) or inspect.ismethod(entry.wrapper) or callable(entry.wrapper)` — but `callable()` already covers all three. Keep as-is.

## Nits

1. Forward marker AD-723a-3a trigger "when 3+ existing entries gain `wrapper` set AND consumer code at `_build_user_message:5977-5990` needs zone-driven iteration instead of the tuple selector" — measurable. ✅
2. Forward marker AD-723a-3b "when prompt-assembly needs deterministic zone ordering across DM and WR paths" — soft. Quantify: "when WR path migration completes (AD-723a-2) AND ordering differences between DM and WR cause observable prompt-output divergence in regression tests."
3. Section 3 test #5 `test_dispatcher_applies_wrapper_to_string_output` — fixture must construct an entry with `output_key="k"` AND `wrapper=lambda s: f"--- A ---\n{s}"`. Frozen dataclass + lambda field — confirm the entry instantiates (lambdas are hashable as identity-only; frozen-dataclass `__hash__` derives from fields, but field-value hashability is required only when calling `hash(entry)`). Tests don't hash the entry, so no issue. Add a one-line note: "tests do not call `hash(entry)`; field-value hashability not required."
4. Section 1 docstring change uses the unique `output_key` line as the SEARCH anchor — good single `replace_string_in_file` candidate. ✅

## Verified

- `SensoriumEntry` class at `cognitive_agent.py:95-115` (frozen `@dataclass`). ✅
- `paths`, `priority`, `output_key` are defaulted; appending new defaulted fields preserves field-ordering rule. ✅
- `_DM_SELF_WRAPPED_KEYS` at line 472 has 2 entries. ✅
- `SENSORIUM_REGISTRY` (21 entries) at line 231 — no SEARCH/REPLACE inside it; entries instantiate identically with new defaulted fields. ✅
- Dispatcher `_dispatch_sensorium_async` exists (per Wave 148 / AD-723a-1 history). ✅
- `SensoriumPath` enum already imported. ✅
- No `multi_replace_string_in_file` adjacency hazard. ✅
- No new pip / npm deps. Apache 2.0 internal.
- Backward-compat assertion: all 21 existing registry entries construct without specifying the new fields (frozen-dataclass default semantics). ✅
- 7 boundary tests cover: zero-field, zone-only, wrapper-only, frozen-immutable, dispatcher-applies-wrapper, dispatcher-skips-on-dict, wrapper-exception-falls-back-to-raw. Covers all branches.

## Build-go criteria

Approved as-is. Recommended fixes are quality-of-life nits, not blockers. LOW risk holds.


### Re-review (pass-2): unchanged, verdict re-affirmed ✅

Prompt was not modified between pass-1 and pass-2 (confirmed: no `## Revision (2026-05-14)` section). Pass-1 verdict (✅ Approved — pure additive frozen-dataclass extension; backward-compatible) stands. The 4 Recommended and 4 Nit findings remain Builder-discretion; none block dispatch.
