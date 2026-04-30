# AD-490 Agent Wiring Security Logs Build Report

**Date:** 2026-04-30
**Status:** Complete
**Prompt:** `prompts/ad-490-agent-wiring-security-logs.md`
**Builder:** ProbOS Builder Agent

## Summary

Moved standard `agent_wired` audit logging until after identity resolution and enriched the structured event-log data with DID, sovereign ID, callsign, and department where available. Red team wiring logs now carry security department context, and `EventType.AGENT_WIRED` is available for downstream consumers while emission sites continue to pass the raw event string to `EventLog.log()`.

No `AGENT_STATE` behavior, identity resolution logic, naming ceremony flow, NATS real-time emission, event-log schema, or non-crew wiring behavior was changed.

## Files Changed

- `src/probos/agent_onboarding.py`
  - Removed premature `agent_wired` log emission before identity resolution.
  - Added enriched `agent_wired` log emission after identity and billet assignment notification.
  - Preserved ontology-first department resolution with standing-orders fallback.
- `src/probos/runtime.py`
  - Added `data={"department": "security"}` to red team `agent_wired` logs.
- `src/probos/events.py`
  - Added `EventType.AGENT_WIRED`.
- `tests/test_ad490_agent_wiring_security_logs.py`
  - Added 7 focused AD-490 tests.
- `PROGRESS.md`, `docs/development/roadmap.md`
  - Updated AD-490 tracking.

## Section Audit

- `### Section 1: Move agent_wired log emission after identity resolution` — implemented in `src/probos/agent_onboarding.py`.
- `### Section 2: Enrich red team agent_wired emission` — implemented in `src/probos/runtime.py`.
- `### Section 3: Add AGENT_WIRED event type constant` — implemented in `src/probos/events.py`.
- `## Tests` — implemented all 7 requested tests.
- `## Tracking` — updated `PROGRESS.md`, `docs/development/roadmap.md`, and this build report.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad490_agent_wiring_security_logs.py -v -n 0`
  - Result: 7 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad490_agent_wiring_security_logs.py tests/test_ad423c_onboarding.py tests/test_onboarding.py tests/test_runtime.py tests/test_events.py -v -n 0`
  - Result: 91 passed, 1 warning.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
  - Result: 10077 passed, 16 skipped, 118 warnings.

## Notes

- No `agent_wired` subscribers were found outside the two event-log emission sites; moving the standard onboarding log after identity resolution only affects audit-log ordering.
- Department resolution precedence is ontology first, then `standing_orders.get_department()`, then `"unassigned"`.
- Red team hardcoded `department="security"` matches the standing-orders classification for `red_team`.
- The full gate used the sweep execution-plan command (`-n 4 --dist=loadfile`) instead of the prompt's older `-n auto` acceptance line.
- Runtime warnings from existing `startup/finalize.py` MagicMock async wiring appeared during the full gate, but the run passed.
