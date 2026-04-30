# AD-675 Uncertainty-Calibrated Initiative Build Report

**Date:** 2026-04-30
**Status:** Complete
**Prompt:** `prompts/ad-675-uncertainty-calibrated-initiative.md`
**Builder:** GitHub Copilot Builder

## Summary

Implemented uncertainty calibration for the AD-674 initiative scale. `UncertaintyContext` now aggregates observation confidence factors, and `calibrate_initiative()` clamps an already-resolved `InitiativeLevel` downward when confidence is low or critical without changing deterministic rank/trust resolution.

## Files Changed

- `src/probos/earned_agency.py`
  - Added `UncertaintyContext`.
  - Added `calibrate_initiative()`.
- `tests/test_ad675_uncertainty_calibrated_initiative.py`
  - Added 6 focused tests for confidence clamping and aggregate confidence.
- `PROGRESS.md`, `docs/development/roadmap.md`
  - Updated AD-675 tracking.
- `prompts/build-reports/ad-675-build.md`
  - Added this build report.

## Sections Implemented

- `### Section 1: Add calibrate_initiative() function`
  - Implemented in `src/probos/earned_agency.py` after `resolve_initiative_level()`.
- `### Section 2: Add UncertaintyContext dataclass`
  - Implemented in `src/probos/earned_agency.py` near `InitiativeLevel`.
- `## Tests`
  - Implemented in `tests/test_ad675_uncertainty_calibrated_initiative.py`.
- `## Tracking`
  - Updated `PROGRESS.md`, `docs/development/roadmap.md`, and this build report.

## Post-Build Section Audit

- `### Section 1: Add calibrate_initiative() function` — complete; high confidence preserves the base initiative level, low confidence clamps down one level, critical confidence clamps down two levels, and the floor is DIRECTED.
- `### Section 2: Add UncertaintyContext dataclass` — complete; frozen dataclass exposes Oracle, health, and freshness factors plus aggregate minimum confidence.
- `## Tests` — complete; 6 focused tests added.
- `## Tracking` — complete; AD-675 marked complete in trackers and build report recorded.

## Tests

- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad675_uncertainty_calibrated_initiative.py -v -n 0`
  - Result: 6 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad675_uncertainty_calibrated_initiative.py tests/test_ad674_graduated_initiative.py tests/test_earned_agency.py -v -n 0`
  - Result: 44 passed.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/ -q -n 4 --dist=loadfile`
  - Result: 1 failed, 10218 passed, 18 skipped.
  - Failure: `tests/test_ad580_alert_feedback.py::TestAlertResolve::test_resolve_refires_after_clean_period`.
- `d:/ProbOS/.venv/Scripts/pytest.exe tests/test_ad580_alert_feedback.py -v -n 0`
  - Result: 21 passed.
  - Classification: environmental parallel full-gate failure per sweep rule; affected file passed serially.

## Deviations

- Used the wave execution plan full-gate command `-n 4 --dist=loadfile` instead of the prompt's older `-n auto` acceptance text.
- Full parallel gate reported one unrelated AD-580 failure; the affected file passed serial rerun and was accepted as environmental under `prompts/BUILDER-EXECUTION-PLAN.md`.
