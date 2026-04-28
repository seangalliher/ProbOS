# Review: AD-594 Crew Consultation Protocol

**Prompt:** `prompts/ad-594-crew-consultation-protocol.md`
**Reviewer:** Architect
**Date:** 2026-04-27 (revision 2)
**Verdict:** ✅ **Approved — ready for builder.**

Previous review (2026-04-27) blocked on three Required items. All resolved.

---

## Required (must fix before building)

_None._

## Recommended (should fix)

1. **`_consultation_protocol: Any = None`** typed as `Any` on `CognitiveAgent`. Use a forward `TYPE_CHECKING` import of `ConsultationProtocol | None` to recover type safety in IDEs/mypy.
2. **`handle_consultation_request` confidence is hardcoded** (0.6 default, 0.2 on LLM failure, 0.1 on no LLM). Confidence should be parsed from the LLM response (the system prompt asks for it). For v1, document this as a known follow-up.
3. **Late-bind via private-attribute access** in Section 5e (`consultation_protocol._capability_registry = ...`) is called out and recommended to be replaced with public setters (`set_capability_registry`, etc.). Builder should add the setters — don't ship the private-access path.

## Nits

4. **Section 5e wiring location** is described as "search for where capability_registry or billet_registry is assigned" — pin the exact module/line in a follow-up to remove builder ambiguity. Acceptable for now since the search target is unambiguous.
5. **`max_completed: 100`** completion log size hardcoded — move to `ConsultationConfig` for tunability.
6. **Tracker section missing** (PROGRESS.md / roadmap / DECISIONS).
7. **No "Do not build" section** — add explicit guards (no multi-round dialogue, no consultation chains > 1 hop, no bypass of trust scoring).

## Verified

- ✅ **Acceptance Criteria block present** with test count (24 tests) and Engineering Principles compliance line.
- ✅ **Silent exception swallow resolved.** Handler dispatch now distinguishes `TimeoutError` → `CONSULTATION_TIMEOUT`, `CancelledError` → re-raise, `Exception` → `CONSULTATION_FAILED` event + warning log with full context.
- ✅ **New `CONSULTATION_FAILED` EventType** added for handler exceptions — failures are now observable, not swallowed.
- ✅ **Typed event dataclasses** (`ConsultationRequestedEvent`, `ConsultationCompletedEvent`, `ConsultationTimeoutEvent`, `ConsultationFailedEvent`) all defined with `event_type` + `init=False`.
- ✅ **Typed config wiring.** `ConsultationConfig` added to `SystemConfig`, constructor accepts typed `config` and reads fields directly. Fallback defaults retained only for the test path with `config=None`.
- ✅ **Rate tracker eviction implemented.** `_check_rate_limit` prunes timestamps older than 1hr **and** deletes empty agent entries to prevent unbounded dict growth.
- ✅ **Urgency enum kept as metadata only** with explicit docstring: "not currently used for queue ordering. The protocol dispatches requests immediately." No false claim of priority arbitration.
- ✅ **Setter injection justified** in docstring: "CognitiveAgent is constructed before ConsultationProtocol exists in the startup sequence."
- ✅ **Pending cap (`max_pending_requests: 10`)** prevents memory leak from unresolved futures.
- ✅ **Future cancellation handling** in `_pending` cleanup path on every exit branch.
- ✅ **`_select_expert` falls back to billet roster scan** when capability registry yields no matches — defense in depth.
- ✅ **Expert selection weights configurable** via `ConsultationConfig.weight_*` fields.
- ✅ **`get_running_loop()` (not `get_event_loop()`)** for future creation.
- ✅ **Rejects empty topic+question** at validation entry.

---

## Recommendation

Ship after the public-setter cleanup (item 3). Items 1–2 and the nits can land in the same iteration. The redesign cleanly addresses every previous concern.
