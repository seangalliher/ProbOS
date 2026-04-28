# AD-594 Crew Consultation Protocol Build Report

**Date:** 2026-04-27
**Status:** Complete
**Prompt:** `prompts/ad-594-crew-consultation-protocol.md`

## Summary

Implemented the Crew Consultation Protocol as a typed in-memory request/response service. Agents can now register consultation handlers, request a directed consultation, or ask the protocol to select an expert using capability, trust, and billet scoring hooks. The protocol enforces hourly per-requester rate limits, a pending cap, and configurable timeout behavior.

## Files Changed

- `src/probos/events.py`
  - Added consultation event types and typed event dataclasses.
- `src/probos/config.py`
  - Added `ConsultationConfig` and `SystemConfig.consultation`.
- `src/probos/cognitive/consultation.py`
  - Added `ConsultationUrgency`, `ConsultationRequest`, `ConsultationResponse`, `_ExpertCandidate`, and `ConsultationProtocol`.
  - Implemented handler registration, request lifecycle, expert selection, rate limiting, timeout/error handling, event emission, diagnostics, and late-bound registry setters.
- `src/probos/cognitive/cognitive_agent.py`
  - Added consultation protocol setter and incoming consultation handler.
- `src/probos/startup/results.py`
  - Added `CognitiveServicesResult.consultation_protocol`.
- `src/probos/startup/cognitive_services.py`
  - Created `ConsultationProtocol` when enabled and returned it from the cognitive services phase.
- `src/probos/runtime.py`
  - Stored the consultation protocol on the runtime from cognitive service results.
- `src/probos/startup/finalize.py`
  - Late-bound capability registry, billet registry, and trust network into the protocol.
  - Wired the protocol to crew agents that expose `set_consultation_protocol()`.
- `tests/test_ad594_consultation_protocol.py`
  - Added 24 focused tests.
- `PROGRESS.md`, `DECISIONS.md`, `docs/development/roadmap.md`
  - Updated AD-594 tracking.

## Section Audit

- `### Section 1: EventType Additions` - implemented in `src/probos/events.py`.
- `### Section 2: ConsultationConfig` - implemented in `src/probos/config.py` and wired into `SystemConfig`.
- `### Section 3: ConsultationProtocol` - implemented in `src/probos/cognitive/consultation.py`, including public late-binding setters.
- `### Section 4: CognitiveAgent Integration` - implemented consultation protocol storage, setter/handler registration, and `handle_consultation_request()`.
- `### Section 5: Startup Wiring` - implemented service creation, result field, runtime assignment, registry late-binding, and crew-agent handler wiring.
- `## Tests` - implemented all 24 requested tests.
- `## Tracking` - updated project trackers and this build report.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad594_consultation_protocol.py::test_config_defaults tests/test_ad594_consultation_protocol.py::test_event_type_members_exist -v -n 0`
  - Result: 2 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad594_consultation_protocol.py -v -n 0`
  - Result: 24 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_cognitive_agent.py -v -x -n 0`
  - Result: 56 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad594_consultation_protocol.py -v -n 0`
  - Result after startup wiring adjustment: 24 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -x -q`
  - Result: stopped on broad xdist worker-crash infrastructure after 9422 passed and 11 skipped. Full output had no AD-594 or consultation-specific failures.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_config.py -v -x -n 0`
  - Result: 3 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_runtime.py -v -x -n 0`
  - Result: 27 passed, 1 warning.

## Notes

- Consultation storage remains in-memory only, as specified.
- No Ward Room, DM routing, API, HXI, persistence, multi-round dialogue, or consultation chaining behavior was added.
- The full-suite failure is the existing xdist worker-crash storm class, not an AD-594 failure.
- `meta.inf` and unrelated review/archive changes remain unstaged and were not part of this build.