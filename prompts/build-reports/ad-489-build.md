# AD-489 Federation Code of Conduct Build Report

**Date:** 2026-04-30
**Status:** Complete
**Prompt:** `prompts/ad-489-federation-code-of-conduct.md`
**Builder:** ProbOS Builder Agent

## Summary

Implemented Federation Code of Conduct standing orders, conduct violation events, and Counselor handling for conduct violation reports. Minor violations now send a private therapeutic DM only; moderate/severe violations record a trust outcome with `source="conduct_violation"` and then send a private DM.

No earned-agency policy, automated violation detection, trust thresholds, cognitive-chain composition logic, shell command, or access-control behavior was changed.

## Files Changed

- `config/standing_orders/federation.md`
  - Added `<!-- category: code_of_conduct -->` and `## Code of Conduct` before core directives.
  - Added six conduct principles and violation handling text.
- `src/probos/events.py`
  - Added `EventType.CONDUCT_VIOLATION`.
- `src/probos/cognitive/counselor.py`
  - Added `CONDUCT_VIOLATION` to Counselor event subscriptions.
  - Routed conduct violation events in `_on_event_async()`.
  - Added `_on_conduct_violation()` with minor-DM and severe-trust-penalty paths.
- `tests/test_ad489_code_of_conduct.py`
  - Added 7 focused AD-489 tests.
- `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`
  - Updated AD-489 tracking and decision record.

## Section Audit

- `### Section 1: Add Code of Conduct text to federation standing orders` — implemented in `config/standing_orders/federation.md`.
- `### Section 2: Add conduct violation event type` — implemented in `src/probos/events.py`.
- `### Section 3: Add conduct violation handler to CounselorAgent` — implemented in Counselor subscription, dispatch, and handler code.
- `### Section 4: Add conduct violation wiring in startup` — verified Counselor receives `add_event_listener_fn` from `startup/finalize.py`; event wiring is handled by Counselor's initialized subscription list, so no finalize.py change was required.
- `## Tests` — implemented all 7 requested tests.
- `## Tracking` — updated `PROGRESS.md`, `docs/development/roadmap.md`, `DECISIONS.md`, and this build report.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad489_code_of_conduct.py -v -n 0`
  - Result: 7 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad489_code_of_conduct.py tests/test_standing_orders.py tests/test_counselor_activation.py tests/test_events.py -v -n 0`
  - Result: 120 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
  - Result: 10070 passed, 16 skipped, 118 warnings.

## Notes

- `<!-- category: code_of_conduct -->` is consumed by the existing StepInstructionRouter path through `get_step_instructions()` when the router is wired; otherwise standing orders fall back to full composition.
- The full gate used the sweep execution-plan command (`-n 4 --dist=loadfile`) instead of the prompt's older `-n auto` acceptance line.
- Runtime warnings from existing `startup/finalize.py` MagicMock async wiring appeared during the full gate, but the run passed.
