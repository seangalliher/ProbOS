# Review: AD-489 — Federation Code of Conduct

**Verdict:** ✅ Approved
**Headline:** Code of Conduct text is clear; Counselor integration follows existing patterns.

## Required

None.

## Recommended

1. **Wire `CONDUCT_VIOLATION` subscription.** Confirm the new `_on_conduct_violation` handler is added to `CounselorAgent._on_event_async` dispatch at [counselor.py:787](src/probos/cognitive/counselor.py#L787). If Counselor doesn't yet subscribe in `__init__`, wire the subscription in [finalize.py:847](src/probos/startup/finalize.py#L847) alongside existing event listeners.
2. **Test DM delivery.** `_send_therapeutic_dm` is heavily used; verify with a mock that the new path calls it with the correct `agent_id` and callsign.
3. **Standing-order category marker.** Prompt adds `<!-- category: code_of_conduct -->`. Verify a `StepInstructionRouter` (or equivalent) actually consumes the marker — otherwise the marker is inert. If consumption is deferred, document so the marker isn't a load-bearing detail today.

## Nits

- Section 1 SEARCH block targets a marker before `## Core Directives`; confirmed at [federation.md:143](config/standing_orders/federation.md#L143).
- "Minor violations: logged" — clarify whether logging is via `logger.info()` or via an `event_log` entry. The two have different operator-visibility implications.

## Verified

- Core Directives at [federation.md:143](config/standing_orders/federation.md#L143).
- `CounselorAgent` at [counselor.py:451](src/probos/cognitive/counselor.py#L451); `_send_therapeutic_dm` at [line 2060](src/probos/cognitive/counselor.py#L2060); `_trust_network` at [line 512](src/probos/cognitive/counselor.py#L512).
- `_on_event_async` dispatch at [counselor.py:787](src/probos/cognitive/counselor.py#L787).
- `TrustNetwork.record_outcome` accepts `source` parameter at [consensus/trust.py:208](src/probos/consensus/trust.py#L208).
- `standing_orders.get_department` at [cognitive/standing_orders.py:70](src/probos/cognitive/standing_orders.py#L70).
- `AGENT_STATE` at [events.py:76](src/probos/events.py#L76) — `CONDUCT_VIOLATION` insertion point confirmed.
