# Review: AD-673 Anomaly Window Detection (Re-review #2)

**Prompt:** prompts/ad-673-anomaly-window-detection.md
**Reviewer:** Architect
**Date:** 2026-04-27 (third pass)
**Verdict:** ✅ Approved
**Previous Verdict:** ⚠️ Conditional

## Improvements Since Prior Review
- **`hasattr` clause REMOVED** from the episode-stamping hook in `episodic.py`. Now uses `if self._anomaly_window_manager is not None:` cleanly.
- **`dataclasses.replace()` used correctly** for both Episode and frozen AnchorFrame — addresses the prior immutability concern.
- **Subscribe-API question RESOLVED** by switching to the existing `_add_event_listener_fn` callback pattern (matches AD-558 and BF-069 wiring). Single async event handler dispatches on `event_type`.
- Signal-source survey done — explicitly confirms `TRUST_CASCADE_WARNING` and `LLM_HEALTH_CHANGED` exist; `ALERT_CONDITION_CHANGED` deferred with a clear note.
- Concurrent signal handling: explicit "concurrent signals merge into one window" semantics; `_affected_count` increment behavior documented.
- Auto-expiry via `max_window_duration_seconds` defends against runaway windows.
- `tag_recent()` documented as a stub returning 0 — interface defined, body deferred. Honest scope.

## Required
None.

## Recommended
- `_wire_anomaly_window` uses `getattr(runtime, "_emit_event", None)` and `getattr(runtime, "_add_event_listener_fn", None)` — same private-attr-access pattern as AD-571. Acceptable in startup wiring per the established convention. Worth tracking in the same future "expose runtime public properties" AD as AD-571's TODOs.

## Nits
- Test 14 (`test_concurrent_signals_single_window`) expects "no second window opened" — verify `open_window` returns the existing ID without emitting a duplicate `ANOMALY_WINDOW_OPENED` event (the spec increments `_affected_count` but doesn't mention re-emission, which is correct).

## Recommendation
Ship it.
